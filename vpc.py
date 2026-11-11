"""
Creates the VPC for the application (assignment step 3):
  - a VPC with DNS hostnames enabled
  - a public and a private subnet in each availability zone
  - an internet gateway and a public route table for the public subnets
"""

import sys

import config
from aws_helpers import ec2, full_name, name_tag


def main():
    vpc_name = full_name("vpc")

    # Don't create a second VPC if this script has already been run
    existing = list(ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]))
    if existing:
        sys.exit(f"{vpc_name} already exists ({existing[0].id})")

    # --- VPC ---
    vpc = ec2.create_vpc(CidrBlock=config.VPC_CIDR)
    vpc.wait_until_available()
    name_tag(vpc, "vpc")
    # Gives instances DNS names like ec2-1-2-3-4.compute-1.amazonaws.com
    vpc.modify_attribute(EnableDnsHostnames={"Value": True})
    print(f"Created VPC {vpc.id} ({config.VPC_CIDR})")

    # --- Internet gateway: the VPC's door to the internet ---
    igw = ec2.create_internet_gateway()
    igw.attach_to_vpc(VpcId=vpc.id)
    name_tag(igw, "igw")
    print(f"Created internet gateway {igw.id}")

    # --- Public route table: send all non-local traffic to the internet gateway ---
    public_rt = vpc.create_route_table()
    public_rt.create_route(DestinationCidrBlock="0.0.0.0/0", GatewayId=igw.id)
    name_tag(public_rt, "rtb-public")
    print(f"Created public route table {public_rt.id}")

    # --- Subnets: one public and one private per availability zone ---
    for i, az in enumerate(config.AZS, start=1):
        public = vpc.create_subnet(CidrBlock=config.PUBLIC_SUBNET_CIDRS[i - 1],
                                   AvailabilityZone=az)
        name_tag(public, f"public{i}-{az}")
        # Instances launched here get a public IP automatically
        ec2.meta.client.modify_subnet_attribute(SubnetId=public.id,
                                                MapPublicIpOnLaunch={"Value": True})
        public_rt.associate_with_subnet(SubnetId=public.id)
        print(f"Created public subnet {public.id} ({public.cidr_block}, {az})")

        # Private subnets stay on the VPC's main route table, which only has
        # the local route, so they can't reach the internet (no NAT yet)
        private = vpc.create_subnet(CidrBlock=config.PRIVATE_SUBNET_CIDRS[i - 1],
                                    AvailabilityZone=az)
        name_tag(private, f"private{i}-{az}")
        print(f"Created private subnet {private.id} ({private.cidr_block}, {az})")

    print("VPC ready.")


if __name__ == "__main__":
    main()