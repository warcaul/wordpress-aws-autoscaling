"""
Launches the bastion host: a minimal instance in a public subnet that is the
only way in for SSH. The web servers and the database accept SSH only from it.
"""

import sys

import boto3

import config

ec2 = boto3.resource("ec2", region_name=config.REGION)
client = boto3.client("ec2", region_name=config.REGION)

BASTION_NAME = f"{config.PROJECT}-bastion"


def find_vpc():
    vpc_name = f"{config.PROJECT}-vpc"
    vpcs = list(ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]))
    if not vpcs:
        sys.exit(f"{vpc_name} not found - run vpc.py first")
    return vpcs[0]


def latest_amazon_linux_ami():
    """Newest official Amazon Linux 2023 image for x86 (t2 instances are x86)."""
    images = client.describe_images(
        Owners=["amazon"],
        Filters=[{"Name": "name", "Values": ["al2023-ami-2023.*-x86_64"]},
                 {"Name": "state", "Values": ["available"]}],
    )["Images"]
    return max(images, key=lambda image: image["CreationDate"])["ImageId"]


def main():
    vpc = find_vpc()

    # Only one bastion: stop if one already exists (running or stopped)
    existing = list(vpc.instances.filter(Filters=[
        {"Name": "tag:Name", "Values": [BASTION_NAME]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
    ]))
    if existing:
        sys.exit(f"{BASTION_NAME} already exists ({existing[0].id}, {existing[0].state['Name']})")

    subnet = list(vpc.subnets.filter(Filters=[
        {"Name": "tag:Name", "Values": [f"{config.PROJECT}-public1-*"]}]))[0]
    security_group = list(vpc.security_groups.filter(Filters=[
        {"Name": "group-name", "Values": [f"{config.PROJECT}-bastion-sg"]}]))[0]

    instance = ec2.create_instances(
        ImageId=latest_amazon_linux_ami(),
        InstanceType=config.INSTANCE_TYPE,
        KeyName=config.KEY_NAME,
        SubnetId=subnet.id,                 # public subnet: gets a public IP automatically
        SecurityGroupIds=[security_group.id],
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{"ResourceType": "instance",
                            "Tags": [{"Key": "Name", "Value": BASTION_NAME}]}],
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