"""
Creates the launch template for auto scaling (assignment step 4): the blueprint
for every instance the auto scaling group launches.

  py -m scaling.launch_template

Run it again after building a new AMI: it adds a new template version that uses
the newest AMI and makes it the default, so the auto scaling group launches
future instances from the new image. Older versions stay as history.
"""

import sys

from botocore.exceptions import ClientError

import config
from aws_helpers import client, find_security_group, find_vpc, full_name

LT_NAME = full_name("lt")


def newest_ami():
    images = client.describe_images(Owners=["self"], Filters=[
        {"Name": "name", "Values": [full_name("wordpress-*")]},
        {"Name": "state", "Values": ["available"]},
    ])["Images"]
    if not images:
        sys.exit("No AMI found - run: py -m scaling.ami")
    return max(images, key=lambda image: image["CreationDate"])


def default_version_ami():
    """AMI used by the template's default version, or None if there's no template yet."""
    try:
        version = client.describe_launch_template_versions(
            LaunchTemplateName=LT_NAME, Versions=["$Default"])["LaunchTemplateVersions"][0]
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidLaunchTemplateName.NotFoundException":
            return None
        raise
    return version["LaunchTemplateData"]["ImageId"]


def main():
    vpc = find_vpc()
    image = newest_ami()

    template_data = {
        "ImageId": image["ImageId"],
        "InstanceType": config.INSTANCE_TYPE,
        "KeyName": config.KEY_NAME,
        "SecurityGroupIds": [find_security_group(vpc, "web-sg").id],
        "IamInstanceProfile": {"Name": config.INSTANCE_PROFILE},
        # Detailed monitoring: CPU metrics every minute instead of every
        # 5 minutes, so scaling alarms can react sooner
        "Monitoring": {"Enabled": True},
        # Name tag for every instance launched from this template
        "TagSpecifications": [{"ResourceType": "instance",
                               "Tags": [{"Key": "Name", "Value": full_name("web-asg")}]}],
    }

    current_ami = default_version_ami()

    if current_ami is None:
        # First run: create the template (version 1)
        client.create_launch_template(
            LaunchTemplateName=LT_NAME,
            VersionDescription=image["Name"],
            LaunchTemplateData=template_data,
            TagSpecifications=[{"ResourceType": "launch-template",
                                "Tags": [{"Key": "Name", "Value": LT_NAME}]}],
        )
        print(f"Created launch template {LT_NAME} (version 1, AMI {image['Name']})")

    elif current_ami == image["ImageId"]:
        print(f"{LT_NAME} already uses the newest AMI ({image['Name']}) - nothing to do")

    else:
        # Template exists with an older AMI: add a version and make it the default
        version = client.create_launch_template_version(
            LaunchTemplateName=LT_NAME,
            VersionDescription=image["Name"],
            LaunchTemplateData=template_data,
        )["LaunchTemplateVersion"]["VersionNumber"]
        client.modify_launch_template(LaunchTemplateName=LT_NAME, DefaultVersion=str(version))
        print(f"Added version {version} of {LT_NAME} with AMI {image['Name']} (now the default)")


if __name__ == "__main__":
    main()