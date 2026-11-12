"""
Creates a CloudWatch dashboard: one page showing how the application behaves,
for watching auto scaling live (e.g. during testing.load) and for screenshots.

  py -m monitoring.dashboard

Widgets: CPU with the scaling thresholds, the custom metrics (memory, swap,
connections, I/O wait, danger), load balancer requests, group size and
healthy instances, and alarm states.
Safe to run again: the dashboard is replaced with the current layout.
"""

import json
import sys

from botocore.exceptions import ClientError

import config
from aws_helpers import cloudwatch, elb, full_name
from scaling.scaling_policies import (SCALE_IN_THRESHOLD, SCALE_OUT_BIG_STEP,
                                      SCALE_OUT_THRESHOLD)

DASHBOARD_NAME = full_name("dashboard")
ASG_NAME = full_name("asg")


def load_balancer_dimensions():
    """CloudWatch identifies a load balancer and target group by the end part
    of their ARNs, e.g. 'app/a2-lb/50dc6c49...' and 'targetgroup/a2-tg/73e2d6bc...'."""
    try:
        lb_arn = elb.describe_load_balancers(
            Names=[full_name("lb")])["LoadBalancers"][0]["LoadBalancerArn"]
        tg_arn = elb.describe_target_groups(
            Names=[full_name("tg")])["TargetGroups"][0]["TargetGroupArn"]
    except ClientError:
        sys.exit("Load balancer or target group not found - run: py -m scaling.load_balancer")
    return lb_arn.split("loadbalancer/")[1], tg_arn.split(":")[-1]


def graph(title, metrics, x, y, width=12, height=6, stat="Average", y_max=None,
          lines=()):
    """A line graph widget. `lines` adds horizontal markers, e.g. thresholds."""
    properties = {
        "title": title,
        "region": config.REGION,
        "view": "timeSeries",
        "stat": stat,
        "period": 60,
        "metrics": metrics,
        "annotations": {"horizontal": [{"label": label, "value": value}
                                       for label, value in lines]},
    }
    if y_max:
        properties["yAxis"] = {"left": {"min": 0, "max": y_max}}
    return {"type": "metric", "x": x, "y": y, "width": width, "height": height,
            "properties": properties}


def main():
    lb, tg = load_balancer_dimensions()
    alarm_arns = [alarm["AlarmArn"] for alarm in
                  cloudwatch.describe_alarms(AlarmNamePrefix=full_name("cpu-"))["MetricAlarms"]]

    widgets = [
        # Row 1: what the scaling policies react to, and what step 7 adds
        graph("CPU utilization (group average)",
              [["AWS/EC2", "CPUUtilization", "AutoScalingGroupName", ASG_NAME]],
              x=0, y=0, y_max=100,
              lines=[("scale out +1", SCALE_OUT_THRESHOLD),
                     ("scale out +2", SCALE_OUT_BIG_STEP),
                     ("scale in", SCALE_IN_THRESHOLD)]),
        graph("Memory and swap (custom metrics)",
              [["A2/WebServer", "MemoryUtilization", "AutoScalingGroupName", ASG_NAME],
               ["A2/WebServer", "SwapUtilization", "AutoScalingGroupName", ASG_NAME]],
              x=12, y=0, y_max=100),

        # Row 2: traffic, and how many servers handle it
        graph("Requests per minute",
              [["AWS/ApplicationELB", "RequestCount", "LoadBalancer", lb,
                {"label": "total"}],
               ["AWS/ApplicationELB", "RequestCountPerTarget", "TargetGroup", tg,
                "LoadBalancer", lb, {"label": "per instance"}]],
              x=0, y=6, stat="Sum"),
        graph("Web servers",
              [["AWS/AutoScaling", "GroupDesiredCapacity", "AutoScalingGroupName", ASG_NAME,
                {"label": "desired"}],
               ["AWS/AutoScaling", "GroupInServiceInstances", "AutoScalingGroupName", ASG_NAME,
                {"label": "in service"}],
               ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", tg,
                "LoadBalancer", lb, {"label": "healthy (load balancer)"}]],
              x=12, y=6, y_max=config.ASG_MAX_SIZE + 1),

        # Row 3: the rest of the custom metrics
        graph("Connections (custom metrics)",
              [["A2/WebServer", "TCPConnections", "AutoScalingGroupName", ASG_NAME,
                {"label": "all TCP"}],
               ["A2/WebServer", "HTTPConnections", "AutoScalingGroupName", ASG_NAME,
                {"label": "HTTP (port 80)"}]],
              x=0, y=12),
        graph("I/O wait and danger (custom metrics)",
              [["A2/WebServer", "IOWait", "AutoScalingGroupName", ASG_NAME,
                {"label": "I/O wait %"}],
               # Danger is 0 or 1, so it gets its own axis on the right
               ["A2/WebServer", "Danger", "AutoScalingGroupName", ASG_NAME,
                {"label": "danger (0/1)", "yAxis": "right", "stat": "Maximum"}]],
              x=12, y=12),
    ]

    # Row 4: current state of the scaling alarms
    if alarm_arns:
        widgets.append({"type": "alarm", "x": 0, "y": 18, "width": 24, "height": 2,
                        "properties": {"title": "Scaling alarms", "alarms": alarm_arns}})

    cloudwatch.put_dashboard(DashboardName=DASHBOARD_NAME,
                             DashboardBody=json.dumps({"widgets": widgets}))
    print(f"Dashboard {DASHBOARD_NAME} ready:")
    print(f"  https://{config.REGION}.console.aws.amazon.com/cloudwatch/home"
          f"?region={config.REGION}#dashboards:name={DASHBOARD_NAME}")


if __name__ == "__main__":
    main()