#!/bin/bash
#
# Custom CloudWatch metrics for the web servers (assignment step 7).
# Runs every minute (systemd timer) and pushes metrics that EC2 can't see
# from outside the instance:
#   MemoryUtilization - % of RAM in use
#   SwapUtilization   - % of the swap file in use (grows when RAM runs out)
#
#   TCPConnections    - established TCP connections
#   HTTPConnections   - established connections to Apache (port 80)
#   IOWait            - % of CPU time spent waiting for the disk
#   Danger            - 1 when memory is nearly full AND the disk is busy
#                       (the server is swapping and slowing down), else 0
# Each value is sent per instance, and - on auto-scaled instances - also for
# the whole auto scaling group. Credentials come from the instance's IAM role
# (LabInstanceProfile), so none are stored here.

NAMESPACE="A2/WebServer"

# --- Instance identity from the metadata service (IMDSv2) ---
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
metadata() {
    curl -s -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/$1"
}
INSTANCE_ID=$(metadata instance-id)
REGION=$(metadata placement/region)

# --- Memory and swap from /proc/meminfo (values in kB) ---
# Memory: MemAvailable counts memory Linux can free up instantly (e.g. file
# caches), so "in use" = total - available, not total - free
MEMORY=$(awk '/^MemTotal:/ {total=$2} /^MemAvailable:/ {avail=$2}
              END {printf "%.1f", (total - avail) * 100 / total}' /proc/meminfo)
SWAP=$(awk '/^SwapTotal:/ {total=$2} /^SwapFree:/ {free=$2}
            END {if (total > 0) printf "%.1f", (total - free) * 100 / total; else print 0}' /proc/meminfo)

# --- Connections, with ss (netstat isn't installed on Amazon Linux 2023) ---
# tail -n +2 skips the header line
TCP_CONNECTIONS=$(ss -tn state established | tail -n +2 | wc -l)
HTTP_CONNECTIONS=$(ss -tn state established '( sport = :80 )' | tail -n +2 | wc -l)

# --- I/O wait from /proc/stat (iostat isn't installed by default) ---
# The "cpu" line holds total CPU time per state since boot; fields 2-9 are
# user, nice, system, idle, iowait, irq, softirq, steal. Two readings one
# second apart give the share of that second spent waiting for the disk.
cpu_times() {
    awk '/^cpu / {print $6, $2+$3+$4+$5+$6+$7+$8+$9}' /proc/stat
}
read -r IOWAIT_1 TOTAL_1 <<< "$(cpu_times)"
sleep 1
read -r IOWAIT_2 TOTAL_2 <<< "$(cpu_times)"
IOWAIT=$(awk -v a="$IOWAIT_1" -v b="$IOWAIT_2" -v c="$TOTAL_1" -v d="$TOTAL_2" \
    'BEGIN {if (d > c) printf "%.1f", (b - a) * 100 / (d - c); else print 0}')

# --- Danger: memory nearly full while the disk is busy means the server is
# swapping and slowing down. awk compares the decimals as numbers (bash's
# [[ > ]] would compare them as text).
DANGER=$(awk -v m="$MEMORY" -v io="$IOWAIT" 'BEGIN {print (m > 80 && io > 20) ? 1 : 0}')

# --- Send all metrics with one dimension (e.g. InstanceId=i-0abc...) ---
send_metrics() {
    local dimension="Dimensions=[{Name=$1,Value=$2}]"
    aws cloudwatch put-metric-data --region "$REGION" --namespace "$NAMESPACE" --metric-data \
        "MetricName=MemoryUtilization,Value=$MEMORY,Unit=Percent,$dimension" \
        "MetricName=SwapUtilization,Value=$SWAP,Unit=Percent,$dimension" \
        "MetricName=TCPConnections,Value=$TCP_CONNECTIONS,Unit=Count,$dimension" \
        "MetricName=HTTPConnections,Value=$HTTP_CONNECTIONS,Unit=Count,$dimension" \
        "MetricName=IOWait,Value=$IOWAIT,Unit=Percent,$dimension" \
        "MetricName=Danger,Value=$DANGER,Unit=None,$dimension"
}

send_metrics InstanceId "$INSTANCE_ID"

# --- Group-wide values, if this instance belongs to an auto scaling group ---
# (the master web server doesn't, so it only reports per-instance values)
GROUP=$(aws autoscaling describe-auto-scaling-instances --region "$REGION" \
    --instance-ids "$INSTANCE_ID" --query "AutoScalingInstances[0].AutoScalingGroupName" \
    --output text)
if [ -n "$GROUP" ] && [ "$GROUP" != "None" ]; then
    send_metrics AutoScalingGroupName "$GROUP"
fi

echo "memory ${MEMORY}%, swap ${SWAP}%, tcp ${TCP_CONNECTIONS}, http ${HTTP_CONNECTIONS}," \
     "iowait ${IOWAIT}%, danger ${DANGER} (instance $INSTANCE_ID, group ${GROUP:-none})"