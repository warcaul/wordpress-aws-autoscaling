"""
Adds dynamic scaling to the auto scaling group (assignment step 5): step
scaling policies triggered by CloudWatch alarms on the group's average CPU.

  Scale out: CPU >= 50% -> +1 instance, CPU >= 80% -> +2 instances
  Scale in:  CPU <  20% -> -1 instance (never below the group's minimum)

  py -m scaling.scaling_policies

Safe to run again: policies and alarms with the same names are updated in place.
"""

import sys

import config
from aws_helpers import autoscaling, full_name, cloudwatch

ASG_NAME = full_name("asg")

SCALE_OUT_THRESHOLD = 50     # % average CPU
SCALE_OUT_BIG_STEP = 80      # % average CPU: add two instances instead of one
SCALE_IN_THRESHOLD = 20      # % average CPU

# Time a new instance needs before its CPU counts towards the group average;
# until then, the policy won't react to the same alarm again
INSTANCE_WARMUP = 120        # seconds


def create_policy(name, steps):
    """A step scaling policy; returns its ARN, which the alarm will trigger."""
    return autoscaling.put_scaling_policy(
        AutoScalingGroupName=ASG_NAME,
        PolicyName=full_name(name),
        PolicyType="StepScaling",
        AdjustmentType="ChangeInCapacity",     # steps add/remove a number of instances
        MetricAggregationType="Average",
        EstimatedInstanceWarmup=INSTANCE_WARMUP,
        StepAdjustments=steps,
    )["PolicyARN"]


def create_alarm(name, threshold, comparison, minutes, policy_arn):
    """Alarm on the group's average CPU, checked every minute. It goes off
    when the condition holds for `minutes` consecutive minutes."""
    cloudwatch.put_metric_alarm(
        AlarmName=full_name(name),
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "AutoScalingGroupName", "Value": ASG_NAME}],
        Statistic="Average",
        Period=60,
        EvaluationPeriods=minutes,
        Threshold=threshold,
        ComparisonOperator=comparison,
        AlarmActions=[policy_arn],
    )


def main():
    groups = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[ASG_NAME])["AutoScalingGroups"]
    if not groups:
        sys.exit(f"{ASG_NAME} not found - run: py -m scaling.auto_scaling")

    # --- Scale out ---
    # Step bounds are relative to the alarm's threshold (50%):
    #   50% to 80% (0 to +30 above it) -> +1 instance
    #   80% and up (+30 and above)     -> +2 instances
    scale_out_arn = create_policy("scale-out", [
        {"MetricIntervalLowerBound": 0,
         "MetricIntervalUpperBound": SCALE_OUT_BIG_STEP - SCALE_OUT_THRESHOLD,
         "ScalingAdjustment": 1},
        {"MetricIntervalLowerBound": SCALE_OUT_BIG_STEP - SCALE_OUT_THRESHOLD,
         "ScalingAdjustment": 2},
    ])
    # React after 2 busy minutes: quick enough for traffic spikes
    create_alarm("cpu-high", SCALE_OUT_THRESHOLD, "GreaterThanOrEqualToThreshold",
                 minutes=2, policy_arn=scale_out_arn)
    print(f"Scale out: CPU >= {SCALE_OUT_THRESHOLD}% for 2 min -> +1, "
          f">= {SCALE_OUT_BIG_STEP}% -> +2")

    # --- Scale in ---
    # Anything below the threshold (20%) -> -1 instance
    scale_in_arn = create_policy("scale-in", [
        {"MetricIntervalUpperBound": 0, "ScalingAdjustment": -1},
    ])
    # Wait 5 quiet minutes: removing capacity too eagerly would cause
    # flapping when traffic dips briefly
    create_alarm("cpu-low", SCALE_IN_THRESHOLD, "LessThanThreshold",
                 minutes=5, policy_arn=scale_in_arn)
    print(f"Scale in:  CPU < {SCALE_IN_THRESHOLD}% for 5 min -> -1 "
          f"(minimum {config.ASG_MIN_SIZE} instances)")


if __name__ == "__main__":
    main()