# wordpress-aws-autoscaling

Python/boto3 automation for deploying WordPress on AWS: custom VPC, MariaDB in a
private subnet, custom AMI, application load balancer, auto scaling with
CloudWatch alarms, and custom metrics.

DevOps Assignment 2.

## Architecture

- **VPC** `10.0.0.0/16` across three availability zones, each with a public and a private subnet
- **Application load balancer** in the public subnets, forwarding HTTP to the web servers
- **Auto scaling group** of WordPress web servers (2 to 4 `t2.nano` instances) in the public
  subnets, launched from a custom AMI
- **MariaDB database** in a private subnet, reachable only from the web servers
- **Bastion host**, the only way in for SSH; web servers and database accept SSH only from it
- **NAT gateway**, so the private database can download packages
- **Step scaling** on average CPU: +1 instance at 50%, +2 at 80%, -1 below 20%
- **Custom metrics** pushed to CloudWatch every minute from each web server: memory, swap,
  TCP and HTTP connections, I/O wait, and a combined "danger" flag

## Project layout

```
config.py              shared settings (region, names, network layout, sizes)
aws_helpers.py         shared boto3 clients and lookups
deploy.py              builds everything in order with one command
teardown.py            deletes everything (keeps the key pair)
network/               key pair, VPC, security groups, NAT gateway
bastion/               bastion host
database/              MariaDB server and its first-boot script
web/                   WordPress master, first-boot script, instance info page, metrics script
scaling/               AMI, load balancer, launch template, auto scaling group, scaling policies
testing/               test traffic, server log check, CPU load
monitoring/            CloudWatch dashboard
```

## Requirements

- Python 3 with boto3: `py -m pip install boto3`
- AWS credentials in `~/.aws/credentials` (on Windows `C:\Users\<you>\.aws\credentials`).
  In the AWS Academy Learner Lab, copy them from **AWS Details → AWS CLI**; they change
  every lab session.
- OpenSSH (`ssh`), included with Windows 10/11, Linux and macOS

## Setup

Copy the secrets template and fill in real values. `.env` is ignored by Git.

```
copy .env.example .env      (Linux/macOS: cp .env.example .env)
```

```
A2_DB_PASSWORD=...          database password (letters and digits only)
A2_WP_ADMIN_USER=...        WordPress admin username (not "admin")
A2_WP_ADMIN_PASSWORD=...    WordPress admin password (letters and digits only)
A2_WP_ADMIN_EMAIL=...       WordPress admin email (valid format; no email is sent)
```

## Deploy

Run all scripts from the repository root.

```
py deploy.py
```

Takes about 15–30 minutes. Steps that already exist are skipped, so it can be run again
after fixing a problem. At the end it prints the site address. Optionally:

```
py -m monitoring.dashboard
```

The NAT gateway is only needed while servers install packages. To save credit afterwards:

```
py -m network.nat_gateway delete
```

## Test

```
py -m testing.traffic                       # 100 requests, tally per instance
py -m testing.server_logs --run <run ID>    # the same run counted in each server's Apache log
py -m testing.cpu_load                      # load the servers' CPUs to trigger scaling
py -m testing.cpu_load --stop               # stop the load early
```

`testing/load.py` generates load with outside web traffic instead. **Avoid it in AWS
Academy**: heavy traffic from one address can get the account flagged.

## Updating the web servers

After changing anything in `web/`, rebuild the master and the AMI, and add a launch
template version:

```
(terminate a2-master-web in the EC2 console first)
py -m web.web_master
py -m scaling.ami --rebuild
py -m scaling.launch_template
```

New auto-scaled instances use the new AMI; replace running ones by terminating them.

## SSH access

Through the bastion; the scripts print ready-made commands. General form:

```
ssh -i ~/.ssh/a2-key.pem -o ProxyCommand="ssh -i ~/.ssh/a2-key.pem -W %h:%p ec2-user@<bastion IP>" ec2-user@<private IP>
```

## Teardown

```
py teardown.py
```

Lists everything it will delete and asks for confirmation. The key pair is kept, and the
CloudWatch dashboard, if created, is deleted manually in the console.