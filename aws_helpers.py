"""
Shared helpers used by the deployment scripts, so common lookups are
written once.
"""

import re
import sys

import boto3

import config

# One EC2 resource and client for all scripts, plus the load balancer
# client (elbv2 = Elastic Load Balancing version 2: application load balancers)
ec2 = boto3.resource("ec2", region_name=config.REGION)
client = boto3.client("ec2", region_name=config.REGION)
elb = boto3.client("elbv2", region_name=config.REGION)


def full_name(name):
    """Project-prefixed name, e.g. full_name('vpc') -> 'a2-vpc'."""
    return f"{config.PROJECT}-{name}"


def name_tag(resource, name):
    """Give an existing resource a Name tag."""
    resource.create_tags(Tags=[{"Key": "Name", "Value": full_name(name)}])


def tag_spec(resource_type, name):
    """Name tag in the TagSpecifications format, for tagging at creation."""
    return [{"ResourceType": resource_type,
             "Tags": [{"Key": "Name", "Value": full_name(name)}]}]


def find_vpc():
    """The project VPC; stops the script if vpc.py hasn't been run yet."""
    vpcs = list(ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [full_name("vpc")]}]))
    if not vpcs:
        sys.exit(f"{full_name('vpc')} not found - run: py -m network.vpc")
    return vpcs[0]


def find_subnets(vpc, pattern):
    """Subnets whose Name tag matches a pattern, e.g. 'public*' or 'private1-*'."""
    return list(vpc.subnets.filter(
        Filters=[{"Name": "tag:Name", "Values": [full_name(pattern)]}]))


def find_security_group(vpc, name):
    """A project security group by name, e.g. 'web-sg'."""
    groups = list(vpc.security_groups.filter(
        Filters=[{"Name": "group-name", "Values": [full_name(name)]}]))
    if not groups:
        sys.exit(f"{full_name(name)} not found - run: py -m network.security_groups")
    return groups[0]


def latest_amazon_linux_ami():
    """Newest official Amazon Linux 2023 image for x86 (t2 instances are x86)."""
    images = client.describe_images(
        Owners=["amazon"],
        Filters=[{"Name": "name", "Values": ["al2023-ami-2023.*-x86_64"]},
                 {"Name": "state", "Values": ["available"]}],
    )["Images"]
    return max(images, key=lambda image: image["CreationDate"])["ImageId"]


def check_user_data(script, source):
    """Stop before launching if the User Data can't work: an empty file, a
    missing #!/bin/bash line (cloud-init would silently skip the script), or a
    placeholder that wasn't filled in (e.g. a typo in its name).
    Placeholders look like __DB_HOST__; PHP's own __DIR__ has no inner
    underscore, so it isn't mistaken for one."""
    if not script.startswith("#!/bin/bash"):
        sys.exit(f"{source} is empty or doesn't start with #!/bin/bash")
    unfilled = sorted(set(re.findall(r"__[A-Z]+_[A-Z_]+__", script)))
    if unfilled:
        sys.exit(f"{source} has unfilled placeholders: {', '.join(unfilled)}")
    return script