"""
Builds the whole system with one command, by running every step in order:

  py deploy.py

Steps that already exist are skipped, so it's safe to run again, for example
after fixing a problem that stopped it halfway. Remove everything with:

  py teardown.py
"""

import sys
import time
import config

from botocore.exceptions import ClientError, NoCredentialsError

import bastion.bastion
import database.database
import network.key_pair
import network.nat_gateway
import network.security_groups
import network.vpc
import scaling.ami
import scaling.auto_scaling
import scaling.launch_template
import scaling.load_balancer
import scaling.scaling_policies
import web.web_master
from aws_helpers import elb, find_vpc, full_name

# (step name, function that performs it), in dependency order
STEPS = [
    ("Key pair",          network.key_pair.main),
    ("VPC",               network.vpc.main),
    ("Security groups",   network.security_groups.main),
    ("NAT gateway",       lambda: network.nat_gateway.create(find_vpc())),
    ("Bastion host",      bastion.bastion.main),
    ("Database server",   database.database.main),
    ("WordPress master",  web.web_master.main),
    ("Custom AMI",        scaling.ami.main),
    ("Load balancer",     scaling.load_balancer.main),
    ("Launch template",   scaling.launch_template.main),
    ("Auto scaling group", scaling.auto_scaling.main),
    ("Scaling policies",  scaling.scaling_policies.main),
]


def minutes_and_seconds(seconds):
    return f"{int(seconds) // 60}m {int(seconds) % 60:02d}s"


def main():
    started = time.time()

    for number, (name, step) in enumerate(STEPS, start=1):
        print(f"\n=== Step {number}/{len(STEPS)}: {name} ===")
        step_started = time.time()
        try:
            step()
        except SystemExit as e:
            # A step stopped on purpose (e.g. something it needs is missing);
            # its message says what to do
            sys.exit(f"\nDeploy stopped at step {number} ({name}): {e}")
        except NoCredentialsError:
            sys.exit("\nNo AWS credentials - update C:\\Users\\<you>\\.aws\\credentials "
                     "from the Learner Lab's AWS Details")
        except ClientError as e:
            error = e.response["Error"]
            sys.exit(f"\nDeploy stopped at step {number} ({name}): "
                     f"AWS error {error['Code']} - {error['Message']}")
        print(f"--- {name} done in {minutes_and_seconds(time.time() - step_started)}")

    dns_name = elb.describe_load_balancers(Names=[full_name("lb")])["LoadBalancers"][0]["DNSName"]
    print(f"\n=== Deploy complete in {minutes_and_seconds(time.time() - started)} ===")
    print(f"Site:          http://{dns_name}")
    print(f"Instance info: http://{dns_name}/instance-info.php")
    print(f"WordPress admin: http://{dns_name}/wp-admin (user '{config.WP_ADMIN_USER}', "
          "password from .env)")
    print("The NAT gateway is only needed while servers install packages; to save credit:")
    print("  py -m network.nat_gateway delete")


if __name__ == "__main__":
    main()