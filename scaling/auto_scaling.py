"""
Creates the auto scaling group (assignment step 4): launches web servers from
the launch template across the public subnets, and registers them with the
load balancer's target group automatically.

  py -m scaling.auto_scaling

Scaling policies (when to add or remove instances) are a separate step.
"""

import sys
import time

from botocore.exceptions import ClientError

import config
from aws_helpers import autoscaling, elb, find_subnets, find_vpc, full_name
from scaling.launch_template import LT_NAME, default_version_ami

ASG_NAME = full_name("asg")


def target_group_arn():
    try:
        return elb.describe_target_groups(
            Names=[full_name("tg")])["TargetGroups"][0]["TargetGroupArn"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "TargetGroupNotFound":
            sys.exit(f"{full_name('tg')} not found - run: py -m scaling.load_balancer")
        raise


def wait_for_healthy_targets(tg_arn, expected, timeout=600):
    """Instances count as ready once the load balancer's health checks pass."""
    print(f"Waiting for {expected} healthy instance(s) in {full_name('tg')}...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        targets = elb.describe_target_health(TargetGroupArn=tg_arn)["TargetHealthDescriptions"]
        states = [t["TargetHealth"]["State"] for t in targets]
        healthy = states.count("healthy")
        print(f"  {healthy}/{expected} healthy  {states}")
        if healthy >= expected:
            return
        time.sleep(15)
    print("Timed out waiting - check the target group's Targets tab in the console")


def main():
    vpc = find_vpc()

    existing = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[ASG_NAME])["AutoScalingGroups"]
    if existing:
        sys.exit(f"{ASG_NAME} already exists")
    if default_version_ami() is None:
        sys.exit(f"{LT_NAME} not found - run: py -m scaling.launch_template")
    tg_arn = target_group_arn()

    autoscaling.create_auto_scaling_group(
        AutoScalingGroupName=ASG_NAME,
        # $Default: always the template version marked default, so a new
        # AMI version is used for instances launched after it
        LaunchTemplate={"LaunchTemplateName": LT_NAME, "Version": "$Default"},
        MinSize=config.ASG_MIN_SIZE,
        DesiredCapacity=config.ASG_DESIRED_CAPACITY,
        MaxSize=config.ASG_MAX_SIZE,
        # One public subnet per availability zone, comma-separated
        VPCZoneIdentifier=",".join(subnet.id for subnet in find_subnets(vpc, "public*")),
        TargetGroupARNs=[tg_arn],
        # Replace instances that fail the load balancer's health check, not
        # only those EC2 reports as broken; give new ones 2 minutes to boot first
        HealthCheckType="ELB",
        HealthCheckGracePeriod=120,
        # Tags the group itself; instance names come from the launch template
        Tags=[{"Key": "Name", "Value": ASG_NAME, "PropagateAtLaunch": False}],
    )
    print(f"Created {ASG_NAME} (min {config.ASG_MIN_SIZE}, desired "
          f"{config.ASG_DESIRED_CAPACITY}, max {config.ASG_MAX_SIZE})")

    # Group size and instance counts as CloudWatch metrics, every minute
    autoscaling.enable_metrics_collection(AutoScalingGroupName=ASG_NAME, Granularity="1Minute")

    wait_for_healthy_targets(tg_arn, config.ASG_DESIRED_CAPACITY)

    dns_name = elb.describe_load_balancers(Names=[full_name("lb")])["LoadBalancers"][0]["DNSName"]
    print(f"\nSite:          http://{dns_name}")
    print(f"Instance info: http://{dns_name}/instance-info.php (refresh to see it change)")


if __name__ == "__main__":
    main()