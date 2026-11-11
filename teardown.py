"""
Deletes everything this project created, in an order AWS accepts:
instances -> NAT gateway -> security groups -> subnets, route tables,
internet gateway -> VPC.

  py teardown.py

The key pair (a2-key) is kept, so the saved .pem file stays usable.
Safe to run again if interrupted: anything already gone is skipped.
"""

import sys
import time

from botocore.exceptions import ClientError

from aws_helpers import client, ec2, full_name
from network.nat_gateway import active_nat_gateways
from network.nat_gateway import delete as delete_nat_gateway


def find_vpc_or_none():
    vpcs = list(ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [full_name("vpc")]}]))
    return vpcs[0] if vpcs else None


def leftover_elastic_ips():
    """The NAT gateway's Elastic IP, if a previous teardown stopped before releasing it."""
    addresses = client.describe_addresses(Filters=[
        {"Name": "tag:Name", "Values": [full_name("nat-eip")]}])["Addresses"]
    return [a for a in addresses if "AssociationId" not in a]


def delete_with_retry(action, description, attempts=10, delay=10):
    """Some deletions fail for a short while after the things that used them
    are gone (e.g. network interfaces still detaching); keep trying."""
    for attempt in range(1, attempts + 1):
        try:
            action()
            print(f"  deleted {description}")
            return
        except ClientError as e:
            if attempt == attempts:
                raise
            print(f"  {description} still in use ({e.response['Error']['Code']}), retrying...")
            time.sleep(delay)


def main():
    vpc = find_vpc_or_none()
    if not vpc:
        sys.exit(f"{full_name('vpc')} not found - nothing to delete")

    # --- Find everything first, so you can review it before anything is deleted ---
    instances = list(vpc.instances.filter(Filters=[{
        "Name": "instance-state-name",
        "Values": ["pending", "running", "stopping", "stopped"]}]))
    nat_gateways = active_nat_gateways(vpc)
    security_groups = [sg for sg in vpc.security_groups.all() if sg.group_name != "default"]
    subnets = list(vpc.subnets.all())
    route_tables = [rt for rt in vpc.route_tables.all()
                    if not any(a.get("Main") for a in rt.associations_attribute)]
    internet_gateways = list(vpc.internet_gateways.all())

    print(f"This will delete {full_name('vpc')} ({vpc.id}) and everything in it:")
    print(f"  {len(instances)} instance(s): "
          + ", ".join(next((t["Value"] for t in i.tags or [] if t["Key"] == "Name"), i.id)
                      for i in instances))
    print(f"  {len(nat_gateways)} NAT gateway(s)")
    print(f"  {len(security_groups)} security group(s): "
          + ", ".join(sg.group_name for sg in security_groups))
    print(f"  {len(subnets)} subnet(s), {len(route_tables)} route table(s), "
          f"{len(internet_gateways)} internet gateway(s)")
    print("The key pair is kept.")
    if input("Type 'yes' to continue: ").strip().lower() != "yes":
        sys.exit("Cancelled - nothing deleted")

    # --- 1. Instances: everything else is in use while they exist ---
    if instances:
        print("Terminating instances...")
        for instance in instances:
            instance.terminate()
        client.get_waiter("instance_terminated").wait(InstanceIds=[i.id for i in instances])
        print("  all instances terminated")

    # --- 2. NAT gateway and its Elastic IP (same logic as network.nat_gateway) ---
    if nat_gateways:
        print("Deleting NAT gateway...")
        delete_nat_gateway(vpc)
    for address in leftover_elastic_ips():
        client.release_address(AllocationId=address["AllocationId"])
        print(f"  released leftover Elastic IP {address['AllocationId']}")

    # --- 3. Security groups: remove rules first, because the groups refer
    #        to each other and a referenced group can't be deleted ---
    if security_groups:
        print("Deleting security groups...")
        for sg in security_groups:
            if sg.ip_permissions:
                sg.revoke_ingress(IpPermissions=sg.ip_permissions)
        for sg in security_groups:
            delete_with_retry(sg.delete, sg.group_name)

    # --- 4. Subnets, route tables, internet gateway, then the VPC itself ---
    print("Deleting network...")
    for subnet in subnets:
        delete_with_retry(subnet.delete, f"subnet {subnet.id}")
    for route_table in route_tables:
        delete_with_retry(route_table.delete, f"route table {route_table.id}")
    for igw in internet_gateways:
        igw.detach_from_vpc(VpcId=vpc.id)
        delete_with_retry(igw.delete, f"internet gateway {igw.id}")
    delete_with_retry(vpc.delete, f"VPC {vpc.id}")

    print("Teardown complete. Key pair kept.")


if __name__ == "__main__":
    main()