"""
Launches the bastion host: a minimal instance in a public subnet that is the
only way in for SSH. The web servers and the database accept SSH only from it.
"""


import config
from aws_helpers import (ec2, find_security_group, find_subnets, find_vpc, full_name,
                         latest_amazon_linux_ami, tag_spec)

BASTION_NAME = full_name("bastion")


def main():
    vpc = find_vpc()

    # Only one bastion: stop if one already exists (running or stopped)
    existing = list(vpc.instances.filter(Filters=[
        {"Name": "tag:Name", "Values": [BASTION_NAME]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
    ]))
    if existing:
        print(f"{BASTION_NAME} already exists ({existing[0].id}, "
              f"{existing[0].state['Name']}) - skipping")
        return

    subnet = find_subnets(vpc, "public1-*")[0]
    security_group = find_security_group(vpc, "bastion-sg")

    instance = ec2.create_instances(
        ImageId=latest_amazon_linux_ami(),
        InstanceType=config.INSTANCE_TYPE,
        KeyName=config.KEY_NAME,
        SubnetId=subnet.id,                 # public subnet: gets a public IP automatically
        SecurityGroupIds=[security_group.id],
        MinCount=1,
        MaxCount=1,
        TagSpecifications=tag_spec("instance", "bastion"),
    )[0]
    print(f"Launched {BASTION_NAME} ({instance.id}), waiting for it to run...")

    instance.wait_until_running()
    instance.reload()                       # refresh to get the public IP
    ip = instance.public_ip_address

    print(f"{BASTION_NAME} running at {ip}")
    print("\nConnect to the bastion:")
    print(f'  ssh -i "{config.KEY_FILE}" ec2-user@{ip}')
    # -J would be shorter, but command-line options like -i aren't applied to
    # the jump host, so ProxyCommand passes the key to both connections
    print("\nConnect to a private instance through the bastion:")
    print(f'  ssh -i "{config.KEY_FILE}" '
          f'-o ProxyCommand="ssh -i {config.KEY_FILE} -W %h:%p ec2-user@{ip}" '
          f'ec2-user@<private IP>')


if __name__ == "__main__":
    main()