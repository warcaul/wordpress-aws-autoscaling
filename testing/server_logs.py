"""
Shows how test traffic was distributed, from the web servers' own Apache
access logs (assignment step 6, second way: server logs).

  py -m testing.server_logs --run 20261112-143005   # one run of testing.traffic
  py -m testing.server_logs                         # all test runs so far

Connects to every in-service instance of the auto scaling group through the
bastion and counts the matching requests in /var/log/httpd/access_log.
"""

import argparse
import os
import re
import subprocess
import sys

import config
from aws_helpers import autoscaling, ec2, find_vpc, full_name

ACCESS_LOG = "/var/log/httpd/access_log"


def bastion_ip(vpc):
    bastions = list(vpc.instances.filter(Filters=[
        {"Name": "tag:Name", "Values": [full_name("bastion")]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]))
    if not bastions:
        sys.exit(f"{full_name('bastion')} is not running - run: py -m bastion.bastion")
    return bastions[0].public_ip_address


def web_servers():
    """(instance ID, availability zone, private IP) of each in-service instance."""
    groups = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[full_name("asg")])["AutoScalingGroups"]
    if not groups:
        sys.exit(f"{full_name('asg')} not found - run: py -m scaling.auto_scaling")
    servers = []
    for member in groups[0]["Instances"]:
        if member["LifecycleState"] == "InService":
            instance = ec2.Instance(member["InstanceId"])
            servers.append((instance.id, member["AvailabilityZone"],
                            instance.private_ip_address))
    return servers


def ssh_through_bastion(bastion, private_ip, command):
    """Run a command on a private instance, jumping through the bastion.
    Auto-scaled instances come and go, and new ones can reuse an old IP with
    a different host key, so host keys aren't checked or saved (test-only)."""
    no_host_keys = ["-o", "StrictHostKeyChecking=no",
                    "-o", f"UserKnownHostsFile={os.devnull}",
                    "-o", "LogLevel=ERROR"]
    proxy = (f"ssh -i {config.KEY_FILE} -o StrictHostKeyChecking=no "
             f"-o UserKnownHostsFile={os.devnull} -o LogLevel=ERROR "
             f"-W %h:%p ec2-user@{bastion}")
    result = subprocess.run(
        ["ssh", "-i", config.KEY_FILE, *no_host_keys, "-o", f"ProxyCommand={proxy}",
         f"ec2-user@{private_ip}", command],
        capture_output=True, text=True, timeout=60)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description="Count test requests in each server's log")
    parser.add_argument("--run", help="run ID printed by testing.traffic")
    args = parser.parse_args()

    if args.run:
        # The run ID goes into a remote shell command, so only allow its own format
        if not re.fullmatch(r"[0-9-]+", args.run):
            sys.exit("A run ID looks like 20261112-143005")
        pattern = f"run={args.run}&"
    else:
        pattern = "instance-info.php?run="       # every test run, not health checks

    vpc = find_vpc()
    bastion = bastion_ip(vpc)
    servers = web_servers()

    # Line 1: number of matching requests; then the last two of them as a sample.
    # The log is only readable by root, hence sudo.
    command = (f"sudo grep -c '{pattern}' {ACCESS_LOG}; "
               f"sudo grep '{pattern}' {ACCESS_LOG} | tail -n 2")

    print(f"Requests in each server's {ACCESS_LOG} matching '{pattern}':\n")
    total = 0
    for instance_id, zone, private_ip in servers:
        lines = ssh_through_bastion(bastion, private_ip, command).splitlines()
        if not lines:
            print(f"  {instance_id}  {zone}  could not read the log")
            continue
        count = int(lines[0])
        total += count
        print(f"  {instance_id}  {zone}  {count:4d} requests")
        for sample in lines[1:]:
            print(f"      {sample}")
    print(f"\n  total: {total} requests")


if __name__ == "__main__":
    main()