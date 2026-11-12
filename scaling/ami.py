"""
Creates a custom AMI from the WordPress master web server (assignment step 2).
Auto-scaled instances are launched from this image.

  py -m scaling.ami              # skips if an AMI already exists
  py -m scaling.ami --rebuild    # always creates a new one (e.g. after changing the master)

Waits until the master actually serves pages before creating the image,
so the AMI never captures a half-finished installation.
"""

import argparse
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

from aws_helpers import client, find_vpc, full_name


def find_master(vpc):
    masters = list(vpc.instances.filter(Filters=[
        {"Name": "tag:Name", "Values": [full_name("master-web")]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]))
    if not masters:
        sys.exit(f"{full_name('master-web')} is not running - run: py -m web.web_master")
    return masters[0]


def wait_until_serving(ip, timeout=900):
    """'Running' only means the instance booted; the User Data may still be
    installing. Apache starts last, so a working page means setup is done."""
    url = f"http://{ip}/instance-info.php"
    print(f"Waiting for {url} to respond...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    print("Master is serving pages")
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(15)
    sys.exit(f"No response from {url} after {timeout} s - check the master's cloud-init log")


def existing_ami():
    images = client.describe_images(Owners=["self"], Filters=[
        {"Name": "name", "Values": [full_name("wordpress-*")]},
        {"Name": "state", "Values": ["available", "pending"]},
    ])["Images"]
    return max(images, key=lambda image: image["CreationDate"]) if images else None


def main(rebuild=False):
    vpc = find_vpc()
    if not rebuild:
        image = existing_ami()
        if image:
            print(f"AMI {image['Name']} already exists - skipping "
                  "(use --rebuild for a new one)")
            return
    master = find_master(vpc)
    vpc = find_vpc()
    master = find_master(vpc)
    wait_until_serving(master.public_ip_address)

    # Date and time in the name, so each new version of the image is distinct
    ami_name = f"{full_name('wordpress')}-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
    name_tag = [{"Key": "Name", "Value": ami_name}]

    # By default AWS reboots the instance for a consistent disk snapshot,
    # so the master is briefly offline while this starts
    ami_id = client.create_image(
        InstanceId=master.id,
        Name=ami_name,
        Description="WordPress web server for auto scaling",
        TagSpecifications=[
            {"ResourceType": "image", "Tags": name_tag},
            {"ResourceType": "snapshot", "Tags": name_tag},   # the disk copy behind the AMI
        ],
    )["ImageId"]
    print(f"Creating AMI {ami_name} ({ami_id}), this takes a few minutes...")

    client.get_waiter("image_available").wait(
        ImageIds=[ami_id], WaiterConfig={"Delay": 15, "MaxAttempts": 80})
    print(f"AMI {ami_id} is available")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create the WordPress AMI")
    parser.add_argument("--rebuild", action="store_true",
                        help="create a new AMI even if one already exists")
    main(rebuild=parser.parse_args().rebuild)