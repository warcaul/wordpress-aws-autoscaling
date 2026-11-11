"""
Creates the application load balancer (assignment step 4):
  - a target group: the web servers that receive traffic (filled in later by auto scaling)
  - an internet-facing load balancer in the public subnets
  - a listener on HTTP port 80 that forwards to the target group

  py -m scaling.load_balancer
"""

import sys

from botocore.exceptions import ClientError

from aws_helpers import elb, find_security_group, find_subnets, find_vpc, full_name

LB_NAME = full_name("lb")
TG_NAME = full_name("tg")

# Plain PHP page, no database involved: an instance is healthy if Apache and
# PHP work. A database problem would otherwise mark every instance unhealthy
# at once, since they all share the same database.
HEALTH_CHECK_PATH = "/instance-info.php"


def load_balancer_exists():
    try:
        elb.describe_load_balancers(Names=[LB_NAME])
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "LoadBalancerNotFound":
            return False
        raise


def main():
    vpc = find_vpc()
    if load_balancer_exists():
        sys.exit(f"{LB_NAME} already exists")

    name_tag = [{"Key": "Name", "Value": LB_NAME}]

    # --- Target group ---
    target_group_arn = elb.create_target_group(
        Name=TG_NAME,
        Protocol="HTTP",
        Port=80,
        VpcId=vpc.id,
        TargetType="instance",
        HealthCheckPath=HEALTH_CHECK_PATH,
        HealthCheckIntervalSeconds=15,
        HealthyThresholdCount=2,         # 2 good checks in a row -> healthy
        UnhealthyThresholdCount=2,       # 2 failed checks in a row -> unhealthy
        Tags=[{"Key": "Name", "Value": TG_NAME}],
    )["TargetGroups"][0]["TargetGroupArn"]

    # When an instance is removed, wait 30 s (default 300 s) for its open
    # requests to finish. Keeps scale-in and teardown quick.
    elb.modify_target_group_attributes(TargetGroupArn=target_group_arn, Attributes=[
        {"Key": "deregistration_delay.timeout_seconds", "Value": "30"}])
    print(f"Created target group {TG_NAME} (health check {HEALTH_CHECK_PATH})")

    # --- Load balancer: one public subnet per availability zone ---
    load_balancer = elb.create_load_balancer(
        Name=LB_NAME,
        Subnets=[subnet.id for subnet in find_subnets(vpc, "public*")],
        SecurityGroups=[find_security_group(vpc, "lb-sg").id],
        Scheme="internet-facing",
        Type="application",
        IpAddressType="ipv4",
        Tags=name_tag,
    )["LoadBalancers"][0]
    print(f"Creating load balancer {LB_NAME} (takes a few minutes)...")
    elb.get_waiter("load_balancer_available").wait(
        LoadBalancerArns=[load_balancer["LoadBalancerArn"]])

    # --- Listener: HTTP on port 80, forwarded to the target group ---
    elb.create_listener(
        LoadBalancerArn=load_balancer["LoadBalancerArn"],
        Protocol="HTTP",
        Port=80,
        DefaultActions=[{"Type": "forward", "TargetGroupArn": target_group_arn}],
    )

    print(f"Load balancer ready: http://{load_balancer['DNSName']}")
    print("It has no web servers yet - the auto scaling group adds them later.")


if __name__ == "__main__":
    main()