"""
Triggers the CPU scaling policies by loading the web servers' CPUs from
inside, instead of sending outside traffic (which AWS Academy can flag as an
attack). Shows the scaling as it happens.

  py -m testing.cpu_load                 # 10 minutes of load
  py -m testing.cpu_load --minutes 5
  py -m testing.cpu_load --stop          # stop the load on all servers now

On every in-service web server it starts `yes > /dev/null`, which keeps one
CPU core at 100%, wrapped in `timeout` so it always stops by itself.
Ctrl+C stops the load early.
"""

import argparse
import time

from testing.load import scaling_status
from testing.server_logs import bastion_ip, ssh_through_bastion, web_servers
from aws_helpers import find_vpc

STOP_COMMAND = "sudo pkill -x yes; true"


def run_on_all(bastion, servers, command):
    for instance_id, zone, private_ip in servers:
        ssh_through_bastion(bastion, private_ip, command)
        print(f"  {instance_id}  {zone}  done")


def main():
    parser = argparse.ArgumentParser(description="Load the web servers' CPUs to trigger scaling")
    parser.add_argument("--minutes", type=int, default=10)
    parser.add_argument("--stop", action="store_true", help="stop the load now")
    args = parser.parse_args()

    bastion = bastion_ip(find_vpc())
    servers = web_servers()

    if args.stop:
        print("Stopping CPU load:")
        run_on_all(bastion, servers, STOP_COMMAND)
        return

    # nohup + redirecting all input/output lets SSH return straight away while
    # the load keeps running; timeout ends it even if this script is closed
    seconds = args.minutes * 60
    start_command = f"nohup timeout {seconds} yes > /dev/null 2>&1 < /dev/null &"

    print(f"Before: {scaling_status()}")
    print(f"\nStarting {args.minutes} minutes of CPU load on {len(servers)} server(s):")
    run_on_all(bastion, servers, start_command)
    print("\nWatching scaling (Ctrl+C stops the load early)...\n")

    started = time.time()
    try:
        while time.time() - started < seconds:
            time.sleep(15)
            elapsed = int(time.time() - started)
            print(f"[{elapsed // 60:2d}:{elapsed % 60:02d}] {scaling_status()}")
    except KeyboardInterrupt:
        print("\nStopping the load early:")
        run_on_all(bastion, servers, STOP_COMMAND)

    print("\nLoad finished. The group scales back in after about 5 quiet minutes.")
    print(f"After: {scaling_status()}")


if __name__ == "__main__":
    main()