"""
Secures the load balancer with HTTPS (additional functionality):
  - opens port 443 on the load balancer's security group
  - creates a self-signed certificate for the load balancer's DNS name
    and imports it into AWS Certificate Manager (ACM)
  - adds an HTTPS listener on port 443 that forwards to the target group
  - turns the HTTP listener on port 80 into a redirect to HTTPS

  py -m scaling.https_listener

Browsers warn about the certificate because it isn't signed by a trusted
certificate authority; a trusted one needs a registered domain name.
Traffic between the load balancer and the web servers stays plain HTTP
inside the VPC. Safe to run again: finished steps are skipped.
"""

import sys
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import config
from aws_helpers import elb, find_security_group, find_vpc, full_name

acm = boto3.client("acm", region_name=config.REGION)

CERT_NAME = full_name("cert")
# Current AWS-recommended policy: TLS 1.2 and 1.3 only
SSL_POLICY = "ELBSecurityPolicy-TLS13-1-2-2021-06"


def find_load_balancer():
    try:
        return elb.describe_load_balancers(Names=[full_name("lb")])["LoadBalancers"][0]
    except ClientError as e:
        if e.response["Error"]["Code"] == "LoadBalancerNotFound":
            sys.exit(f"{full_name('lb')} not found - run: py -m scaling.load_balancer")
        raise


def allow_https(vpc):
    """Open port 443 on a2-lb-sg, if an older deployment doesn't have it yet."""
    try:
        find_security_group(vpc, "lb-sg").authorize_ingress(IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "HTTPS from anywhere"}]}])
        print("Opened port 443 on a2-lb-sg")
    except ClientError as e:
        if e.response["Error"]["Code"] != "InvalidPermission.Duplicate":
            raise


def self_signed_certificate(dns_name):
    """A 3072-bit RSA key and a certificate for dns_name, valid for a year,
    both as PEM text (the format ACM imports)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IE"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DevOps Assignment 2"),
        x509.NameAttribute(NameOID.COMMON_NAME, dns_name),
    ])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)                 # self-signed: issuer is the subject itself
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))   # tolerate small clock differences
        .not_valid_after(now + timedelta(days=365))
        # Browsers check the Subject Alternative Name, not the Common Name
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(dns_name)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.TraditionalOpenSSL,
                                serialization.NoEncryption())
    return certificate_pem, key_pem


def certificate_arn(dns_name):
    """The ACM certificate for this load balancer: an existing one, or a new
    self-signed one. The private key is only kept in memory and in ACM."""
    for summary in acm.list_certificates()["CertificateSummaryList"]:
        if summary["DomainName"] == dns_name:
            print(f"Certificate for {dns_name} already in ACM - reusing it")
            return summary["CertificateArn"]

    certificate_pem, key_pem = self_signed_certificate(dns_name)
    arn = acm.import_certificate(Certificate=certificate_pem, PrivateKey=key_pem,
                                 Tags=[{"Key": "Name", "Value": CERT_NAME}])["CertificateArn"]
    print(f"Imported self-signed certificate {CERT_NAME} for {dns_name} into ACM")
    return arn


def main():
    vpc = find_vpc()
    load_balancer = find_load_balancer()
    lb_arn, dns_name = load_balancer["LoadBalancerArn"], load_balancer["DNSName"]
    tg_arn = elb.describe_target_groups(
        Names=[full_name("tg")])["TargetGroups"][0]["TargetGroupArn"]

    allow_https(vpc)
    cert_arn = certificate_arn(dns_name)

    listeners = {listener["Port"]: listener
                 for listener in elb.describe_listeners(LoadBalancerArn=lb_arn)["Listeners"]}

    # --- HTTPS on 443: decrypts at the load balancer, forwards HTTP to the servers ---
    if 443 in listeners:
        print("HTTPS listener already exists - skipping")
    else:
        elb.create_listener(
            LoadBalancerArn=lb_arn, Protocol="HTTPS", Port=443,
            SslPolicy=SSL_POLICY,
            Certificates=[{"CertificateArn": cert_arn}],
            DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}],
        )
        print(f"Created HTTPS listener on port 443 ({SSL_POLICY})")

    # --- HTTP on 80: permanent redirect to the same address over HTTPS ---
    if 80 in listeners:
        elb.modify_listener(ListenerArn=listeners[80]["ListenerArn"], DefaultActions=[{
            "Type": "redirect",
            "RedirectConfig": {"Protocol": "HTTPS", "Port": "443", "StatusCode": "HTTP_301"},
        }])
        print("HTTP listener on port 80 now redirects to HTTPS")

    print(f"\nSite: https://{dns_name}")
    print("Expect a browser warning: the certificate is self-signed.")


if __name__ == "__main__":
    main()