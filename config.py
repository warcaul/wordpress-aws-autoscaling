"""Shared settings for the deployment scripts."""

import os

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