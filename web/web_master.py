"""
Launches the WordPress "master" web server in a public subnet. The custom AMI
for auto scaling is built from this instance later.

  py -m web.web_master

Requires the database server (database.database) to be running.
"""

import os
import sys

import config
from aws_helpers import (check_user_data, ec2, find_security_group, find_subnets, find_vpc,
                         full_name, latest_amazon_linux_ami, tag_spec)

MASTER_NAME = full_name("master-web")
HERE = os.path.dirname(os.path.abspath(__file__))
USERDATA_FILE = os.path.join(HERE, "userdata.sh")
INSTANCE_INFO_FILE = os.path.join(HERE, "instance-info.php")
METRICS_FILE = os.path.join(HERE, "metrics.sh")


def database_private_ip(vpc):
    """Private IP of the running database server; WordPress connects to it."""
    databases = list(vpc.instances.filter(Filters=[
        {"Name": "tag:Name", "Values": [full_name("db")]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]))
    if not databases:
        sys.exit(f"{full_name('db')} is not running - run: py -m database.database")
    return databases[0].private_ip_address


def build_user_data(db_host):
    """Read userdata.sh, fill in the placeholders, and insert the PHP page and the metrics script."""
    with open(USERDATA_FILE) as f:          # text mode: \r\n becomes \n
        script = f.read()
    with open(INSTANCE_INFO_FILE) as f:
        instance_info_page = f.read().rstrip("\n")
    if not instance_info_page.startswith("<?php"):
        sys.exit(f"{INSTANCE_INFO_FILE} is empty or doesn't start with <?php")
    with open(METRICS_FILE) as f:
        metrics_script = f.read().rstrip("\n")
    if not metrics_script.startswith("#!/bin/bash"):
        sys.exit(f"{METRICS_FILE} is empty or doesn't start with #!/bin/bash")

    values = {
        "__DB_HOST__": db_host,
        "__DB_NAME__": config.DB_NAME,
        "__DB_USER__": config.DB_USER,
        "__DB_PASSWORD__": config.db_password(),
        "__INSTANCE_INFO_PHP__": instance_info_page,
        "__METRICS_SH__": metrics_script,
    }
    for placeholder, value in values.items():
        script = script.replace(placeholder, value)
    return check_user_data(script, USERDATA_FILE)


def main():
    vpc = find_vpc()

    existing = list(vpc.instances.filter(Filters=[
        {"Name": "tag:Name", "Values": [MASTER_NAME]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
    ]))
    if existing:
        print(f"{MASTER_NAME} already exists ({existing[0].id}, "
              f"{existing[0].state['Name']}) - skipping")
        return

    db_host = database_private_ip(vpc)
    print(f"Database server at {db_host}")

    instance = ec2.create_instances(
        ImageId=latest_amazon_linux_ami(),
        InstanceType=config.INSTANCE_TYPE,
        KeyName=config.KEY_NAME,
        SubnetId=find_subnets(vpc, "public1-*")[0].id,    # public: gets a public IP
        SecurityGroupIds=[find_security_group(vpc, "web-sg").id],
        IamInstanceProfile={"Name": config.INSTANCE_PROFILE},
        UserData=build_user_data(db_host),
        MinCount=1,
        MaxCount=1,
        TagSpecifications=tag_spec("instance", "master-web"),
    )[0]
    print(f"Launched {MASTER_NAME} ({instance.id}), waiting for it to run...")

    instance.wait_until_running()
    instance.reload()
    ip = instance.public_ip_address
    print(f"{MASTER_NAME} running at {ip}")
    print("Apache, PHP and WordPress install in the background; allow about 5 minutes.")
    print(f"\n  WordPress setup: http://{ip}")
    print(f"  Instance info:   http://{ip}/instance-info.php")


if __name__ == "__main__":
    main()