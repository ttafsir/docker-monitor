import argparse
import sys
from collections import defaultdict
from pathlib import Path

try:
    from ansible import context
    from ansible.cli import CLI
    from ansible.cli.inventory import InventoryCLI
except ImportError:
    sys.exit("Ansible is not installed. Please install by running: pip install ansible")

from templates import TemplateBuilder


def cli_parser():
    parser = argparse.ArgumentParser(description="create pyats testbed for clab.")
    parser.add_argument("-i", "--inventory", help="file path of the inventory file")
    parser.add_argument("-t", "--topo", help="clab topology")
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


def generate_testbed_vars(host_vars):
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

        device["alias"] = h

        if "ansible_network_os" not in h_vars:
            raise Exception("Missing key word 'ansible_network_os' for %s" % h)

        device["os"] = h_vars["ansible_network_os"]
        device["platform"] = h_vars["ansible_network_os"]
        testbed["devices"].update({h: dict(device)})
    return testbed


def render_testbed(template: str = None, data: dict = None):
    template_builder = TemplateBuilder(template_dir="templates")
    return template_builder.render_template(template, data)


def main():
    args = cli_parser()
    host_vars = ansible_inventory_vars(host="all", inventory=args.inventory)
    testbed_vars = generate_testbed_vars(host_vars)
    testbed_vars.update({"name": args.topo})
    testbed = render_testbed(template="pyats_template.j2", data=testbed_vars)

    if Path(args.topo).exists() and Path(args.topo).is_dir():
        fp = Path(args.topo) / "testbed.yaml"
        fp.write_text(testbed)


if __name__ == "__main__":
    main()
