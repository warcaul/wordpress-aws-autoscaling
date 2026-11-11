"""
Creates the security groups for the application (assignment step 3):
  - a2-bastion-sg: SSH from my IP only (the single entry point for admin access)
  - a2-lb-sg:      HTTP from anywhere (the public entry point for users)
  - a2-web-sg:     HTTP from the load balancer (and my IP, for testing),
                   SSH from the bastion
  - a2-db-sg:      MySQL from the web servers, SSH from the bastion
"""

import sys
import urllib.request

from aws_helpers import find_vpc, full_name


def my_public_ip():
    """Ask AWS which public IP this PC's requests come from."""
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10) as response:
        return response.read().decode().strip()


def create_group(vpc, name, description):
    group_name = full_name(name)
    sg = vpc.create_security_group(GroupName=group_name, Description=description)
    sg.create_tags(Tags=[{"Key": "Name", "Value": group_name}])
    print(f"Created {group_name} ({sg.id})")
    return sg


def allow_from_ip(port, cidr, description):
    """Inbound rule: allow a TCP port from an IP range."""
    return {"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
            "IpRanges": [{"CidrIp": cidr, "Description": description}]}


def allow_from_group(port, group, description):
    """Inbound rule: allow a TCP port from any instance in another security group."""
    return {"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
            "UserIdGroupPairs": [{"GroupId": group.id, "Description": description}]}


def main():
    vpc = find_vpc()

    # Don't create duplicates if this script has already been run
    existing = list(vpc.security_groups.filter(
        Filters=[{"Name": "group-name", "Values": [full_name("*")]}]))
    if existing:
        sys.exit("Security groups already exist: "
                 + ", ".join(sg.group_name for sg in existing))

    my_ip = f"{my_public_ip()}/32"      # /32 = exactly this one address
    print(f"Your public IP: {my_ip}")

    # Create all groups first, so rules can refer to each other
    bastion = create_group(vpc, "bastion-sg", "Bastion: SSH from my IP")
    lb = create_group(vpc, "lb-sg", "Load balancer: HTTP from anywhere")
    web = create_group(vpc, "web-sg", "Web servers: HTTP from LB, SSH from bastion")
    db = create_group(vpc, "db-sg", "Database: MySQL from web servers, SSH from bastion")

    bastion.authorize_ingress(IpPermissions=[
        allow_from_ip(22, my_ip, "SSH from my IP"),
    ])
    lb.authorize_ingress(IpPermissions=[
        allow_from_ip(80, "0.0.0.0/0", "HTTP from anywhere"),
    ])
    web.authorize_ingress(IpPermissions=[
        allow_from_group(80, lb, "HTTP from load balancer"),
        allow_from_ip(80, my_ip, "HTTP from my IP for testing"),
        allow_from_group(22, bastion, "SSH from bastion"),
    ])
    db.authorize_ingress(IpPermissions=[
        allow_from_group(3306, web, "MySQL from web servers"),
        allow_from_group(22, bastion, "SSH from bastion"),
    ])
    print("Inbound rules added. Security groups ready.")


if __name__ == "__main__":
    main()