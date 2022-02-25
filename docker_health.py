import asyncio
import argparse
import logging
import sys

import docker


client = docker.from_env()


log = logging.getLogger("docker-monitor")
log.addHandler(logging.StreamHandler())


def cli_parser():
    parser = argparse.ArgumentParser(description="Process some integers.")
    parser.add_argument(
        "--delay", default=30, help="sum the integers (default: find the max)"
    )
    parser.add_argument(
        "--retries", default=20, help="number of retries to check containers"
    )
    parser.add_argument(
        "--prefix", default="clab", help="prefix for the container names"
    )
    parser.add_argument("--log", default="INFO", help="log level")
    return parser.parse_args()


def get_log_level(log_level: str):
    log_levels = ("NOTSET", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    if log_level.upper() not in log_levels:
        log_level = "INFO"
    return getattr(logging, log_level)


async def main():
    """
    Monitor the container health checks until they are all running
    or the retries are maxed out.

    Example:
        python docker_health.py --prefix clab --retries 20 --delay 30
    """
    args = cli_parser()
    prefix = args.prefix
    delay = int(args.delay)
    retries = int(args.retries)

    log_level = get_log_level(args.log)
    log.setLevel(log_level)

    running_containers = client.containers.list()
    if prefix:
        to_check = [c.name for c in running_containers if c.name.startswith(prefix)]
    else:
        to_check = [c.name for c in running_containers]

    if not to_check:
        log.debug("No containers to check")
        sys.exit(0)

    while to_check and retries > 0:
        running_containers = client.containers.list()

        log.debug("Checking containers: {}".format(to_check))
        for container in running_containers:
            status = container.attrs["State"].get("Health", {}).get("Status", "N/A")
            log.debug("=>{}:{}".format(container.name, status))

            if status is None:
                to_check.pop(0)

            if status == "healthy":
                log.debug("Container {} is healthy".format(container.name))
                to_check.pop(0)

        if to_check:
            retries -= 1
            await asyncio.sleep(delay)

    if to_check:
        log.error("Health check timed for: {}".format(to_check))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
