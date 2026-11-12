"""
Launches the database server (MariaDB) in a private subnet.

  py -m database.database

Requires the NAT gateway, so the instance can download packages on first boot.
"""

import os
import sys

import config
from aws_helpers import (check_user_data, client, ec2, find_security_group, find_subnets,
                         find_vpc, full_name, latest_amazon_linux_ami, tag_spec)

DB_INSTANCE_NAME = full_name("db")
USERDATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "userdata.sh")


def nat_gateway_available(vpc):
    nat_gateways = client.describe_nat_gateways(Filters=[
        {"Name": "vpc-id", "Values": [vpc.id]},
        {"Name": "state", "Values": ["available"]},
    ])["NatGateways"]
    return bool(nat_gateways)


def build_user_data():
    """Read userdata.sh and fill in the placeholders."""
    # Text mode turns Windows line endings (\r\n) into \n while reading,
    # so the script reaches the instance in Linux format
    with open(USERDATA_FILE) as f:
        script = f.read()

    # "10.0.0.0/16" -> "10.0.%": MySQL's wildcard for any address in the VPC
    allowed_hosts = ".".join(config.VPC_CIDR.split(".")[:2]) + ".%"

    values = {
        "__DB_NAME__": config.DB_NAME,
        "__DB_USER__": config.DB_USER,
        "__DB_PASSWORD__": config.db_password(),
        "__ALLOWED_HOSTS__": allowed_hosts,
    }
    for placeholder, value in values.items():
        script = script.replace(placeholder, value)
    return check_user_data(script, USERDATA_FILE)


def bastion_ip(vpc):
    """Public IP of the running bastion, for the SSH hint (or None)."""
    bastions = list(vpc.instances.filter(Filters=[
        {"Name": "tag:Name", "Values": [full_name("bastion")]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]))
    return bastions[0].public_ip_address if bastions else None


def main():
    vpc = find_vpc()

    if not nat_gateway_available(vpc):
        sys.exit("No NAT gateway - run: py -m network.nat_gateway create")

    existing = list(vpc.instances.filter(Filters=[
        {"Name": "tag:Name", "Values": [DB_INSTANCE_NAME]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
    ]))
    if existing:
        print(f"{DB_INSTANCE_NAME} already exists ({existing[0].id}, "
              f"{existing[0].state['Name']}) - skipping")
        return

    instance = ec2.create_instances(
        ImageId=latest_amazon_linux_ami(),
        InstanceType=config.INSTANCE_TYPE,
        KeyName=config.KEY_NAME,
        SubnetId=find_subnets(vpc, "private1-*")[0].id,   # private: no public IP
        SecurityGroupIds=[find_security_group(vpc, "db-sg").id],
        UserData=build_user_data(),
        MinCount=1,
        MaxCount=1,
        TagSpecifications=tag_spec("instance", "db"),
    )[0]
    print(f"Launched {DB_INSTANCE_NAME} ({instance.id}), waiting for it to run...")

    instance.wait_until_running()
    instance.reload()
    private_ip = instance.private_ip_address
    print(f"{DB_INSTANCE_NAME} running at private IP {private_ip}")
    print("MariaDB installs in the background; allow about 5 minutes.")

    bastion = bastion_ip(vpc)
    if bastion:
        print("\nTo check the installation, connect through the bastion:")
        print(f'  ssh -i "{config.KEY_FILE}" '
              f'-o ProxyCommand="ssh -i {config.KEY_FILE} -W %h:%p ec2-user@{bastion}" '
              f'ec2-user@{private_ip}')
        print("  sudo tail -20 /var/log/cloud-init-output.log")
    else:
        print("\nNo running bastion - start one with: py -m bastion.bastion")


if __name__ == "__main__":
    main()