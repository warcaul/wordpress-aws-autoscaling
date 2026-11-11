#!/bin/bash
#
# Custom CloudWatch metrics for the web servers (assignment step 7).
# Runs every minute (systemd timer) and pushes two metrics that EC2 can't
# see from outside the instance:
#   MemoryUtilization - % of RAM in use
#   SwapUtilization   - % of the swap file in use (grows when RAM runs out)
#
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

# --- Measurements from /proc/meminfo (values in kB) ---
# Memory: MemAvailable counts memory Linux can free up instantly (e.g. file
# caches), so "in use" = total - available, not total - free
MEMORY=$(awk '/^MemTotal:/ {total=$2} /^MemAvailable:/ {avail=$2}
              END {printf "%.1f", (total - avail) * 100 / total}' /proc/meminfo)
SWAP=$(awk '/^SwapTotal:/ {total=$2} /^SwapFree:/ {free=$2}
            END {if (total > 0) printf "%.1f", (total - free) * 100 / total; else print 0}' /proc/meminfo)

# --- Send per-instance values ---
aws cloudwatch put-metric-data --region "$REGION" --namespace "$NAMESPACE" --metric-data \
    "MetricName=MemoryUtilization,Value=$MEMORY,Unit=Percent,Dimensions=[{Name=InstanceId,Value=$INSTANCE_ID}]" \
    "MetricName=SwapUtilization,Value=$SWAP,Unit=Percent,Dimensions=[{Name=InstanceId,Value=$INSTANCE_ID}]"

# --- Send group-wide values, if this instance belongs to an auto scaling group ---
# (the master web server doesn't, so it only reports per-instance values)
GROUP=$(aws autoscaling describe-auto-scaling-instances --region "$REGION" \
    --instance-ids "$INSTANCE_ID" --query "AutoScalingInstances[0].AutoScalingGroupName" \
    --output text)
if [ -n "$GROUP" ] && [ "$GROUP" != "None" ]; then
    aws cloudwatch put-metric-data --region "$REGION" --namespace "$NAMESPACE" --metric-data \
        "MetricName=MemoryUtilization,Value=$MEMORY,Unit=Percent,Dimensions=[{Name=AutoScalingGroupName,Value=$GROUP}]" \
        "MetricName=SwapUtilization,Value=$SWAP,Unit=Percent,Dimensions=[{Name=AutoScalingGroupName,Value=$GROUP}]"
fi

echo "memory ${MEMORY}%, swap ${SWAP}% (instance $INSTANCE_ID, group ${GROUP:-none})"