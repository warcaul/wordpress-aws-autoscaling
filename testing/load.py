"""
Generates sustained web traffic to trigger the CPU scaling policies
(demonstrates assignment step 5), and shows the scaling as it happens.

  py -m testing.load                            # 20 parallel users for 10 minutes
  py -m testing.load --users 40 --minutes 5

Many parallel requests to the WordPress homepage keep the web servers' CPUs
busy, since PHP renders each page and queries the database. Every 15 seconds
it prints the request rate, the group's size and the alarm states.
Stop early with Ctrl+C.
"""

import argparse
import sys
import threading
import time
import urllib.error
import urllib.request

from botocore.exceptions import ClientError

from aws_helpers import autoscaling, cloudwatch, elb, full_name

stop = threading.Event()      # tells all user threads to finish
lock = threading.Lock()       # protects the counters, shared by all threads
stats = {"ok": 0, "failed": 0}


def load_balancer_dns():
    try:
        return elb.describe_load_balancers(
            Names=[full_name("lb")])["LoadBalancers"][0]["DNSName"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "LoadBalancerNotFound":
            sys.exit(f"{full_name('lb')} not found - run: py -m scaling.load_balancer")
        raise


def simulated_user(url):
    """One 'user': requests the page again and again until told to stop."""
    while not stop.is_set():
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                response.read()
            outcome = "ok"
        except (urllib.error.URLError, OSError):
            outcome = "failed"
        with lock:
            stats[outcome] += 1


def scaling_status():
    """Group size and alarm states, e.g. 'instances 2/2 (desired 2) | cpu-high OK'."""
    group = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[full_name("asg")])["AutoScalingGroups"]
    if not group:
        return "no auto scaling group"
    in_service = sum(1 for i in group[0]["Instances"] if i["LifecycleState"] == "InService")
    total = len(group[0]["Instances"])
    alarms = cloudwatch.describe_alarms(AlarmNamePrefix=full_name("cpu-"))["MetricAlarms"]
    alarm_states = "  ".join(f"{a['AlarmName']} {a['StateValue']}" for a in alarms)
    return (f"instances {in_service} in service / {total} "
            f"(desired {group[0]['DesiredCapacity']}) | {alarm_states}")


def main():
    parser = argparse.ArgumentParser(description="Generate load to trigger auto scaling")
    parser.add_argument("--users", type=int, default=20, help="parallel simulated users")
    parser.add_argument("--minutes", type=float, default=10)
    args = parser.parse_args()

    url = f"http://{load_balancer_dns()}/"
    print(f"{args.users} users requesting {url} for {args.minutes:g} minutes "
          f"(Ctrl+C to stop early)")
    print(f"Before: {scaling_status()}\n")

    # daemon=True: the threads can't keep the program alive after Ctrl+C
    threads = [threading.Thread(target=simulated_user, args=(url,), daemon=True)
               for _ in range(args.users)]
    for thread in threads:
        thread.start()

    started = time.time()
    deadline = started + args.minutes * 60
    previous_ok = 0
    try:
        while time.time() < deadline:
            time.sleep(15)
            with lock:
                ok, failed = stats["ok"], stats["failed"]
            rate = (ok - previous_ok) / 15
            previous_ok = ok
            elapsed = int(time.time() - started)
            print(f"[{elapsed // 60:2d}:{elapsed % 60:02d}] {rate:5.1f} req/s  "
                  f"ok {ok}  failed {failed} | {scaling_status()}")
    except KeyboardInterrupt:
        print("\nStopped early")
    finally:
        stop.set()

    print(f"\nLoad finished: {stats['ok']} successful, {stats['failed']} failed requests")
    print("The group scales back in after about 5 quiet minutes (cpu-low alarm).")
    print(f"After: {scaling_status()}")


if __name__ == "__main__":
    main()