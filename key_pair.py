"""
Creates the key pair used for SSH access to all instances, and saves the
private key to ~/.ssh (outside the repo) readable only by the current user.
"""

import os
import subprocess
import sys

import boto3
from botocore.exceptions import ClientError

import config

ec2 = boto3.client("ec2", region_name=config.REGION)


def key_exists_in_aws():
    try:
        ec2.describe_key_pairs(KeyNames=[config.KEY_NAME])
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidKeyPair.NotFound":
            return False
        raise


def restrict_permissions(path):
    """Make the key readable only by the current user; ssh refuses keys
    that other users can read."""
    if os.name == "nt":
        # Windows: remove inherited permissions, then grant read to this user only
        user = os.environ["USERNAME"]
        subprocess.run(["icacls", path, "/inheritance:r"], check=True, capture_output=True)
        subprocess.run(["icacls", path, "/grant:r", f"{user}:R"], check=True, capture_output=True)
    else:
        os.chmod(path, 0o400)       # Linux/macOS: read-only for the owner


def main():
    # The private key can only be downloaded once, at creation, so never
    # recreate or overwrite an existing key
    if key_exists_in_aws():
        sys.exit(f"Key pair {config.KEY_NAME} already exists in AWS")
    if os.path.exists(config.KEY_FILE):
        sys.exit(f"{config.KEY_FILE} already exists - not overwriting it")

    response = ec2.create_key_pair(
        KeyName=config.KEY_NAME,
        KeyType="rsa",
        KeyFormat="pem",
        TagSpecifications=[{"ResourceType": "key-pair",
                            "Tags": [{"Key": "Name", "Value": config.KEY_NAME}]}],
    )
    print(f"Created key pair {config.KEY_NAME} in AWS")

    # Save the private key straight away; AWS doesn't keep a copy.
    # newline="\n" keeps Linux line endings, which ssh expects, even on Windows.
    os.makedirs(os.path.dirname(config.KEY_FILE), exist_ok=True)
    with open(config.KEY_FILE, "w", newline="\n") as f:
        f.write(response["KeyMaterial"])
    restrict_permissions(config.KEY_FILE)
    print(f"Private key saved to {config.KEY_FILE} (readable only by you)")


if __name__ == "__main__":
    main()