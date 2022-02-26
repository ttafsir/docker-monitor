import asyncio
import argparse
import logging
import sys

import docker


client = docker.from_env()


LOG = logging.getLogger("docker-health-monitor")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch = logging.StreamHandler()
ch.setFormatter(formatter)
LOG.addHandler(ch)


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


def get_status(container):
    return container.attrs["State"].get("Health", {}).get("Status", "N/A")


def get_docker_health(name: str = None, prefix: str = None):
    """
    Get the status of all containers with the given prefix.
    """
    if not any((name, prefix)):
        raise ValueError("Either name or prefix must be provided")

    if prefix:
        containers = [c for c in client.containers.list() if c.name.startswith(prefix)]
    else:
        containers = client.containers.list(filters={"name": name})

    statuses = []
    for container in containers:
        status = get_status(container)
        if status != "N/A":
            LOG.info("=> {}: {}".format(container.name, status))
            statuses.append((container.name, status))
    return statuses


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
    LOG.setLevel(log_level)

    health = dict(get_docker_health(prefix=prefix))
    while any(status != "healthy" for status in health.values()) and retries > 0:
        LOG.info("Monitoring: {}".format(list(health.keys())))
        await asyncio.sleep(delay)
        retries -= 1
        health.update(dict(get_docker_health(prefix=prefix)))

    if unhealthy := {k: v for k, v in health.items() if v != "healthy"}:
        LOG.error("Health check timed for: {}".format(unhealthy.keys()))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
