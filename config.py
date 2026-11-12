"""Shared settings for the deployment scripts."""

import os
import sys
import ipaddress

# AWS region where everything is created
REGION = "us-east-1"

# Prefix for resource names, e.g. "a2-vpc"
PROJECT = "a2"

# Availability zones to spread subnets across
AZS = ["us-east-1a", "us-east-1b", "us-east-1c"]

# Network layout: the VPC, then one public and one private subnet per AZ
VPC_CIDR = "10.0.0.0/16"
PUBLIC_SUBNET_CIDRS = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
PRIVATE_SUBNET_CIDRS = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]

# The database server's fixed private IP: the 10th address of the first private
# subnet (AWS reserves .0-.3 and the last address). Fixed, so the AMI's
# wp-config.php stays valid when the database is recreated.
DB_PRIVATE_IP = str(ipaddress.ip_network(PRIVATE_SUBNET_CIDRS[0])[10])

# Key pair for SSH access: its name in AWS, and the private key file on this PC
KEY_NAME = f"{PROJECT}-key"
KEY_FILE = os.path.expanduser(f"~/.ssh/{KEY_NAME}.pem")

# Instance type for all servers (512 MB RAM, cheapest general-purpose type)
INSTANCE_TYPE = "t2.nano"

def secret(name):
    """A secret read from an environment variable or from the local .env file
    (which is never committed)."""
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if name not in os.environ and os.path.isfile(env_file):
        with open(env_file) as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key == name:
                    os.environ[name] = value.strip().strip('"')

    value = os.environ.get(name)
    if not value or value == "CHANGE_ME":
        sys.exit(f"Set {name} in .env (copy .env.example to .env)")
    return value


def db_password():
    return secret("A2_DB_PASSWORD")

def wp_admin_user():
    return secret("A2_WP_ADMIN_USER")

def wp_admin_password():
    return secret("A2_WP_ADMIN_PASSWORD")

def wp_admin_email():
    return secret("A2_WP_ADMIN_EMAIL")

# WordPress database: its name and the MariaDB user WordPress connects as
DB_NAME = "wordpress"
DB_USER = "wpuser"

# WordPress site created automatically on first boot. The admin login
# (username, password, email) comes from .env, so it's never published.
WP_TITLE = "DevOps Assignment 2"


# IAM role provided by the Learner Lab; lets instances call AWS (e.g. CloudWatch)
# without storing credentials on them
INSTANCE_PROFILE = "LabInstanceProfile"

# Auto scaling group size: always at least 2 web servers (in different
# availability zones), at most 4 under load
ASG_MIN_SIZE = 2
ASG_DESIRED_CAPACITY = 2
ASG_MAX_SIZE = 4