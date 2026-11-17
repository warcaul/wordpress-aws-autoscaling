"""
Generates test traffic to the load balancer and shows how it was distributed
(assignment step 6, first way: instance metadata).

  py -m testing.traffic                  # 100 requests
  py -m testing.traffic --requests 500

Each request goes to /instance-info.php, which reports the instance that
served it. Every request also carries a run ID in its URL, so the same run
can be found afterwards in the servers' own logs (testing.server_logs).
"""

import argparse
import re
import ssl
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime

from botocore.exceptions import ClientError

from aws_helpers import elb, full_name

# The load balancer's certificate is self-signed, so no trusted authority can
# vouch for it and normal verification would reject it. These test requests
# go to our own load balancer, so skip the check; traffic is still encrypted.
SELF_SIGNED = ssl.create_default_context()
SELF_SIGNED.check_hostname = False
SELF_SIGNED.verify_mode = ssl.CERT_NONE

def load_balancer_dns():
    try:
        return elb.describe_load_balancers(
            Names=[full_name("lb")])["LoadBalancers"][0]["DNSName"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "LoadBalancerNotFound":
            sys.exit(f"{full_name('lb')} not found - run: py -m scaling.load_balancer")
        raise


def table_value(html, label):
    """Read one value from the instance-info.php table, e.g. 'Instance ID'."""
    match = re.search(rf"<b>{label}</b></td><td>([^<]+)</td>", html)
    return match.group(1) if match else "unknown"


def main():
    parser = argparse.ArgumentParser(description="Send test traffic to the load balancer")
    parser.add_argument("--requests", type=int, default=100)
    args = parser.parse_args()

    dns_name = load_balancer_dns()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"Sending {args.requests} requests to https://{dns_name} (run ID {run_id})...")

    served_by = Counter()
    failed = 0
    for n in range(1, args.requests + 1):
        url = f"https://{dns_name}/instance-info.php?run={run_id}&n={n}"
        try:
            with urllib.request.urlopen(url, timeout=10, context=SELF_SIGNED) as response:
                html = response.read().decode()
            served_by[(table_value(html, "Instance ID"),
                       table_value(html, "Availability zone"))] += 1
        except (urllib.error.URLError, OSError):
            failed += 1

    print(f"\nRequests per instance (run {run_id}):")
    for (instance_id, zone), count in served_by.most_common():
        print(f"  {instance_id}  {zone}  {count:4d} requests  "
              f"({count / args.requests:.0%})")
    if failed:
        print(f"  failed: {failed}")

    print(f"\nCheck the servers' own logs for this run:\n"
          f"  py -m testing.server_logs --run {run_id}")


if __name__ == "__main__":
    main()