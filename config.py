"""Shared settings for the deployment scripts."""

import os
import sys

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

# Key pair for SSH access: its name in AWS, and the private key file on this PC
KEY_NAME = f"{PROJECT}-key"
KEY_FILE = os.path.expanduser(f"~/.ssh/{KEY_NAME}.pem")

# Instance type for all servers (512 MB RAM, cheapest general-purpose type)
INSTANCE_TYPE = "t2.nano"

def db_password():
    """The database password, read from the A2_DB_PASSWORD environment
    variable or from a local .env file (which is never committed)."""
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if "A2_DB_PASSWORD" not in os.environ and os.path.isfile(env_file):
        with open(env_file) as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key == "A2_DB_PASSWORD":
                    os.environ["A2_DB_PASSWORD"] = value.strip().strip('"')

    password = os.environ.get("A2_DB_PASSWORD")
    if not password or password == "CHANGE_ME":
        sys.exit("Set A2_DB_PASSWORD in .env (copy .env.example to .env)")
    return password


# WordPress database: its name and the MariaDB user WordPress connects as
DB_NAME = "wordpress"
DB_USER = "wpuser"