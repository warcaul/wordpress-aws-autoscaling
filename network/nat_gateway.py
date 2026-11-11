"""
Gives the private subnets outbound internet access through a NAT gateway.

  py -m network.nat_gateway create   - Elastic IP + NAT gateway + private route table
  py -m network.nat_gateway delete   - removes the NAT gateway and releases its Elastic IP

The NAT gateway costs money while it exists, so delete it when the private
instances don't need to download anything.
"""

import argparse
import sys
import time

from aws_helpers import client, find_subnets, find_vpc, full_name, name_tag, tag_spec


def active_nat_gateways(vpc):
    return client.describe_nat_gateways(Filters=[
        {"Name": "vpc-id", "Values": [vpc.id]},
        {"Name": "state", "Values": ["pending", "available"]},
    ])["NatGateways"]


def create(vpc):
    if active_nat_gateways(vpc):
        sys.exit("A NAT gateway already exists in this VPC")

    # The NAT gateway itself needs internet access, so it goes in a public subnet
    public_subnet = find_subnets(vpc, "public1-*")[0]

    # A fixed public address for the NAT gateway
    allocation_id = client.allocate_address(
        Domain="vpc", TagSpecifications=tag_spec("elastic-ip", "nat-eip"))["AllocationId"]
    print(f"Allocated Elastic IP {allocation_id}")

    nat_id = client.create_nat_gateway(
        SubnetId=public_subnet.id, AllocationId=allocation_id,
        TagSpecifications=tag_spec("natgateway", "nat"))["NatGateway"]["NatGatewayId"]
    print(f"Creating NAT gateway {nat_id} (takes a minute or two)...")
    client.get_waiter("nat_gateway_available").wait(NatGatewayIds=[nat_id])
    print("NAT gateway available")

    # Private route table: reuse it if an earlier run created it
    rt_name = full_name("rtb-private")
    tables = list(vpc.route_tables.filter(Filters=[{"Name": "tag:Name", "Values": [rt_name]}]))
    if tables:
        private_rt = tables[0]
    else:
        private_rt = vpc.create_route_table()
        name_tag(private_rt, "rtb-private")
        for subnet in find_subnets(vpc, "private*"):
            private_rt.associate_with_subnet(SubnetId=subnet.id)
        print(f"Created {rt_name} and associated the private subnets")

    # Send all non-local traffic from the private subnets to the NAT gateway.
    # If a route from an earlier (deleted) NAT gateway is still there, replace it.
    has_default_route = any(r.destination_cidr_block == "0.0.0.0/0" for r in private_rt.routes)
    if has_default_route:
        client.replace_route(RouteTableId=private_rt.id, DestinationCidrBlock="0.0.0.0/0",
                             NatGatewayId=nat_id)
    else:
        private_rt.create_route(DestinationCidrBlock="0.0.0.0/0", NatGatewayId=nat_id)
    print("Private subnets now reach the internet through the NAT gateway")


def delete(vpc):
    nat_gateways = active_nat_gateways(vpc)
    if not nat_gateways:
        sys.exit("No NAT gateway to delete")

    for nat in nat_gateways:
        allocation_ids = [a["AllocationId"] for a in nat["NatGatewayAddresses"]]
        client.delete_nat_gateway(NatGatewayId=nat["NatGatewayId"])
        print(f"Deleting NAT gateway {nat['NatGatewayId']}...")

        # The Elastic IP can only be released once the NAT gateway is gone
        while client.describe_nat_gateways(NatGatewayIds=[nat["NatGatewayId"]])[
                "NatGateways"][0]["State"] != "deleted":
            time.sleep(10)

        for allocation_id in allocation_ids:
            client.release_address(AllocationId=allocation_id)
            print(f"Released Elastic IP {allocation_id}")

    print("NAT gateway deleted. The private route stays, but leads nowhere until "
          "you run 'create' again.")


def main():
    parser = argparse.ArgumentParser(description="Create or delete the NAT gateway")
    parser.add_argument("action", choices=["create", "delete"])
    args = parser.parse_args()

    vpc = find_vpc()
    create(vpc) if args.action == "create" else delete(vpc)


if __name__ == "__main__":
    main()