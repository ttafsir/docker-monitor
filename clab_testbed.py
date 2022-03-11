import argparse
import sys
from collections import defaultdict
from pathlib import Path

import docker

try:
    from ansible import context
    from ansible.cli import CLI
    from ansible.cli.inventory import InventoryCLI
except ImportError:
    sys.exit("Ansible is not installed. Please install by running: pip install ansible")

from templates import TemplateBuilder


TESTBED_TEMPLATE = """
testbed:
    name: {{ name }}
    {% if alias is defined and alias %}
    alias: {{ alias }}
    {% endif %}

devices:
{% for device, attrs in devices.items() %}
  {{ device | replace('clab-', '') | replace(name ~ '-', '') }}:
    connections:
      cli:
        ip: {{ attrs.connections.cli.get('ip') }}
        protocol: {{ attrs.connections.cli.get('protocol', 'ssh') }}
    credentials:
      default:
        password: {{ attrs.get('password', 'admin') }}
        username: {{ attrs.get('username', 'admin') }}
      enable:
        password: {{ attrs.get('enable_password', 'admin') }}
    os: {{ attrs.get('os', 'iosxe') }}
    type: {{ attrs.get('type', 'iosxe') }}
{% endfor %}
"""


def cli_parser():
    parser = argparse.ArgumentParser(description="create pyats testbed for clab.")
    parser.add_argument("-i", "--inventory", help="file path of the inventory file")
    parser.add_argument("-t", "--topo", help="clab topology", required=True)
    parser.add_argument(
        "-o", "--output-dir", default=".", help="output directory for testbed file"
    )
    return parser.parse_args()


class InventoryCLI(InventoryCLI):
    def iter_host_vars(self):
        CLI.run(self)
        self.loader, self.inventory, self.vm = self._play_prereqs()

        for host in self.inventory.get_hosts(context.CLIARGS["host"]):
            yield host, self._get_host_variables(host=host)


def ansible_inventory_vars(host, inventory):
    args = ["ansible-inventory", "--inventory", inventory, "--host", host]
    cli = InventoryCLI(args)
    return cli.iter_host_vars()


def get_docker_container_ips(topo) -> dict:
    docker_client = docker.from_env()
    containers = [c for c in docker_client.containers.list() if topo in c.name]
    container_ips = {}
    for c in containers:
        address = c.attrs["NetworkSettings"]["Networks"]["clab"]["IPAddress"]
        image_name = next((t for t in c.image.tags if "vrnetlab" in t), "")

        # return dict with device IP, name and image
        # fix image name format: vrnetlab/vr-csr:16.12.02s -> csr:16.12.02s
        container_ips.update(
            {address: {"name": c.name, "image": image_name.replace("vrnetlab/vr-", "")}}
        )
    return container_ips


def find_device_type_from_docker_image(image: str) -> str:
    return {
        "nx": "nxos",
        "nxos9kv": "nxos",
        "xr": "iosxr",
        "xrv9k": "iosxr",
        "xrv": "iosxr",
        "csr": "iosxe",
        "ios": "ios",
        "asav": "asa",
        "veos": "eos",
        "ceos": "eos",
        "sros": "sros",
        "vmx": "junos",
        "vqfx": "junos",
    }.get(image)


def generate_testbed_vars(host_vars: dict, topo: str = None):
    container_ips = get_docker_container_ips(topo)

    testbed = {"devices": {}}
    for (h, h_vars) in host_vars:

        # prefer netconf over ssh if defined
        cli_name = (
            "netconf"
            if "ansible_connection" in h_vars
            and "netconf" in h_vars["ansible_connection"]
            else "cli"
        )

        device = defaultdict(dict)
        device["connections"] = {cli_name: {"protocol": "ssh"}}
        device["credentials"] = {"default": {}}

        cli = device["connections"][cli_name]
        cli["ip"] = h_vars["ansible_host"] if "ansible_host" in h_vars else h

        if "ansible_ssh_port" in h_vars:
            cli["port"] = h_vars["ansible_ssh_port"]

        # retrieve password from host vars
        if "ansible_password" in h_vars:
            device["default"].setdefault("password", h_vars["ansible_password"])
            device["default"].setdefault("username", h_vars["ansible_user"])

        if "ansible_become_method" in h_vars and "ansible_become_pass" in h_vars:
            inner = device["connections"][h_vars["ansible_become_method"]]
            inner.setdefault("password", h_vars["ansible_become_pass"])

        if "ansible_network_os" not in h_vars:
            raise Exception("Missing key word 'ansible_network_os' for %s" % h)

        device["alias"] = h
        device["os"] = h_vars["ansible_network_os"]
        device["platform"] = h_vars["ansible_network_os"]

        # use IP address to find our container
        container_data = container_ips.get(cli["ip"])
        if container_data:
            image = container_data["image"].split(":")[0]  # csr:16.12.02s -> csr
            device_type = find_device_type_from_docker_image(image)
            device["os"] = device_type
            device["type"] = device_type
        testbed["devices"].update({h: dict(device)})
    return testbed


def render_testbed(template: str = None, data: dict = None):
    template_builder = TemplateBuilder()
    return template_builder.render_string(template, data)


def main():
    """
    python clab_testbed.py -i hosts.yml --topo testlab --output-dir tests
    """
    args = cli_parser()
    host_vars = ansible_inventory_vars(host="all", inventory=args.inventory)
    testbed_vars = generate_testbed_vars(host_vars, topo=args.topo)
    testbed_vars.update({"name": args.topo})
    testbed = render_testbed(template=TESTBED_TEMPLATE, data=testbed_vars)
    testbed_filepath = Path(args.output_dir) / "testbed.yaml"
    testbed_filepath.write_text(testbed)


if __name__ == "__main__":
    main()
