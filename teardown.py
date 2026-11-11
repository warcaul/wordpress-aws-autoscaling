"""
Deletes everything this project created, in an order AWS accepts:
auto scaling group -> AMIs -> launch template -> load balancer and target
group -> instances -> NAT gateway -> security groups -> subnets, route tables,
internet gateway -> VPC.

  py teardown.py

The key pair (a2-key) is kept, so the saved .pem file stays usable.
Safe to run again if interrupted: anything already gone is skipped.
"""

import sys
import time

from botocore.exceptions import ClientError

from aws_helpers import autoscaling, client, ec2, elb, full_name
from network.nat_gateway import active_nat_gateways
from network.nat_gateway import delete as delete_nat_gateway


def find_vpc_or_none():
    vpcs = list(ec2.vpcs.filter(Filters=[{"Name": "tag:Name", "Values": [full_name("vpc")]}]))
    return vpcs[0] if vpcs else None


def find_auto_scaling_group():
    groups = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[full_name("asg")])["AutoScalingGroups"]
    return groups[0] if groups else None

def project_amis():
    """Our AMIs (named a2-wordpress-...). They live outside the VPC."""
    return client.describe_images(Owners=["self"], Filters=[
        {"Name": "name", "Values": [full_name("wordpress-*")]}])["Images"]


def snapshot_ids(image):
    """The EBS snapshots (disk copies) behind an AMI."""
    return [mapping["Ebs"]["SnapshotId"]
            for mapping in image.get("BlockDeviceMappings", [])
            if "SnapshotId" in mapping.get("Ebs", {})]


def find_launch_template():
    """The launch template (with all its versions), or None. Like AMIs, it
    lives outside the VPC."""
    try:
        return client.describe_launch_templates(
            LaunchTemplateNames=[full_name("lt")])["LaunchTemplates"][0]
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidLaunchTemplateName.NotFoundException":
            return None
        raise


def find_load_balancer():
    try:
        return elb.describe_load_balancers(Names=[full_name("lb")])["LoadBalancers"][0]
    except ClientError as e:
        if e.response["Error"]["Code"] == "LoadBalancerNotFound":
            return None
        raise


def find_target_group():
    try:
        return elb.describe_target_groups(Names=[full_name("tg")])["TargetGroups"][0]
    except ClientError as e:
        if e.response["Error"]["Code"] == "TargetGroupNotFound":
            return None
        raise


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
    auto_scaling_group = find_auto_scaling_group()
    amis = project_amis()
    launch_template = find_launch_template()
    if not vpc and not auto_scaling_group and not amis and not launch_template:
        sys.exit("Nothing to delete")

    # --- Find everything first, so you can review it before anything is deleted ---
    print("This will delete:")
    if auto_scaling_group:
        print(f"  auto scaling group {full_name('asg')} "
              f"with {len(auto_scaling_group['Instances'])} instance(s)")
    print(f"  {len(amis)} AMI(s) and their snapshots: "
          + ", ".join(image["Name"] for image in amis))
    
    if launch_template:
        print(f"  launch template {full_name('lt')} "
        f"({launch_template['LatestVersionNumber']} version(s))")

    if vpc:
        load_balancer = find_load_balancer()
        target_group = find_target_group()
# Instances launched by auto scaling are removed with their group,
# # so only the ones launched by our scripts are listed here
        instances = [i for i in vpc.instances.filter(Filters=[{
            "Name": "instance-state-name",
            "Values": ["pending", "running", "stopping", "stopped"]}])
            if not any(t["Key"] == "aws:autoscaling:groupName" for t in i.tags or [])]
        nat_gateways = active_nat_gateways(vpc)
        security_groups = [sg for sg in vpc.security_groups.all() if sg.group_name != "default"]
        subnets = list(vpc.subnets.all())
        route_tables = [rt for rt in vpc.route_tables.all()
                        if not any(a.get("Main") for a in rt.associations_attribute)]
        internet_gateways = list(vpc.internet_gateways.all())

        print(f"  {full_name('vpc')} ({vpc.id}) and everything in it:")
        print(f"    load balancer: {'yes' if load_balancer else 'none'}, "
              f"target group: {'yes' if target_group else 'none'}")
        print(f"    {len(instances)} instance(s): "
              + ", ".join(next((t["Value"] for t in i.tags or [] if t["Key"] == "Name"), i.id)
                          for i in instances))
        print(f"    {len(nat_gateways)} NAT gateway(s)")
        print(f"    {len(security_groups)} security group(s): "
              + ", ".join(sg.group_name for sg in security_groups))
        print(f"    {len(subnets)} subnet(s), {len(route_tables)} route table(s), "
              f"{len(internet_gateways)} internet gateway(s)")
    print("The key pair is kept.")
    if input("Type 'yes' to continue: ").strip().lower() != "yes":
        sys.exit("Cancelled - nothing deleted")

    # --- 1. Auto scaling group first: otherwise it keeps replacing the
    #        instances we delete. ForceDelete terminates its instances too ---
    if auto_scaling_group:
        if auto_scaling_group.get("Status") != "Delete in progress":
            autoscaling.delete_auto_scaling_group(
                AutoScalingGroupName=full_name("asg"), ForceDelete=True)
        print(f"Deleting {full_name('asg')} and its instances (a few minutes)...")
        while (auto_scaling_group := find_auto_scaling_group()):
            states = [i["LifecycleState"] for i in auto_scaling_group["Instances"]]
            print(f"  still deleting - instances: {', '.join(states) or 'none left'}")
            time.sleep(15)
        print(f"  deleted {full_name('asg')}")

    # --- 2. AMIs: deregister first, then the snapshot can be deleted ---
    for image in amis:
        client.deregister_image(ImageId=image["ImageId"])
        print(f"Deregistered AMI {image['Name']} ({image['ImageId']})")
        for snapshot_id in snapshot_ids(image):
            delete_with_retry(lambda: client.delete_snapshot(SnapshotId=snapshot_id),
                              f"snapshot {snapshot_id}")

    # --- 3. Launch template: deleting it removes all its versions ---
    if launch_template:
        client.delete_launch_template(LaunchTemplateName=full_name("lt"))
        print(f"Deleted launch template {full_name('lt')}")

    if not vpc:
        print("Teardown complete. Key pair kept.")
        return

    # --- 4. Load balancer, then its target group (in use while the LB exists) ---
    if load_balancer:
        print("Deleting load balancer...")
        elb.delete_load_balancer(LoadBalancerArn=load_balancer["LoadBalancerArn"])
        elb.get_waiter("load_balancers_deleted").wait(
            LoadBalancerArns=[load_balancer["LoadBalancerArn"]])
        print(f"  deleted {full_name('lb')}")
    if target_group:
        delete_with_retry(
            lambda: elb.delete_target_group(TargetGroupArn=target_group["TargetGroupArn"]),
            full_name("tg"))

    # --- 5. Instances: everything else is in use while they exist ---
    if instances:
        print("Terminating instances...")
        for instance in instances:
            instance.terminate()
        client.get_waiter("instance_terminated").wait(InstanceIds=[i.id for i in instances])
        print("  all instances terminated")

    # --- 6. NAT gateway and its Elastic IP (same logic as network.nat_gateway) ---
    if nat_gateways:
        print("Deleting NAT gateway...")
        delete_nat_gateway(vpc)
    for address in leftover_elastic_ips():
        client.release_address(AllocationId=address["AllocationId"])
        print(f"  released leftover Elastic IP {address['AllocationId']}")

    # --- 7. Security groups: remove rules first, because the groups refer
    #        to each other and a referenced group can't be deleted ---
    if security_groups:
        print("Deleting security groups...")
        for sg in security_groups:
            if sg.ip_permissions:
                sg.revoke_ingress(IpPermissions=sg.ip_permissions)
        for sg in security_groups:
            delete_with_retry(sg.delete, sg.group_name)

    # --- 8. Subnets, route tables, internet gateway, then the VPC itself ---
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