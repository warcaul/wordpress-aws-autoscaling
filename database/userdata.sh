#!/bin/bash
#
# User Data for the database server: runs once, as root, on first boot.
# Installs MariaDB and creates the WordPress database and user.
#
# The __PLACEHOLDERS__ are replaced by database.py before launch,
# so no real values are stored in this file.

DB_NAME="__DB_NAME__"
DB_USER="__DB_USER__"
DB_PASSWORD="__DB_PASSWORD__"
ALLOWED_HOSTS="__ALLOWED_HOSTS__"     # e.g. 10.0.% = any address in the VPC

# --- Swap: a t2.nano has only 512 MB of RAM ---
dd if=/dev/zero of=/swapfile bs=1M count=1024
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo "/swapfile swap swap defaults 0 0" >> /etc/fstab

# --- OS updates and MariaDB (downloads go through the NAT gateway) ---
dnf update -y
dnf install -y mariadb105-server

# --- Low-memory settings, and accept connections from the network ---
cat > /etc/my.cnf.d/wordpress.cnf <<EOF
[mysqld]
bind-address = 0.0.0.0
innodb_buffer_pool_size = 64M
performance_schema = OFF
max_connections = 50
EOF

systemctl enable --now mariadb

# --- WordPress database and user ---
mysql <<EOF
CREATE DATABASE IF NOT EXISTS ${DB_NAME};
CREATE USER IF NOT EXISTS '${DB_USER}'@'${ALLOWED_HOSTS}' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'${ALLOWED_HOSTS}';
FLUSH PRIVILEGES;
EOF