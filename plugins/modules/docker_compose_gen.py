# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r"""
---
module: docker_compose_gen
short_description: Generate a Docker Compose file
description:
  - Takes a dictionary definition of a Docker Compose structure (services, networks, volumes, etc.)
    and writes it out as a YAML file at the specified destination.
options:
  compose:
    description:
      - Dictionary representing the Compose file structure.
    required: true
    type: dict
  dest:
    description:
      - Path to write the rendered docker-compose YAML.
    required: true
    type: path
  mode:
    description:
      - File mode for the generated file.
    type: str
    default: '0644'
  owner:
    description:
      - Name of the user who should own the generated file, as it should be fed to `chown`.
    type: str
  group:
    description:
      - Name of the group who should own the generated file, as it should be fed to `chown`.
    type: str
  validate:
    description:
      - Whether to validate the generated Docker Compose file using `docker-compose config`.
    type: bool
    default: false
  tool:
    description:
      - Specify the tool to use for validating Docker Compose files.
      - Choices are `docker-compose`, `compose-plugin`, or `auto`.
      - The `auto` option will attempt to detect the available tool.
    type: str
    choices:
      - docker-compose
      - compose-plugin
      - auto
    default: auto
author: Brian Clark (@bdclark)
"""

EXAMPLES = r"""
- name: Generate compose file
  my_namespace.docker.docker_compose_gen:
    compose:
      version: "3.9"
      services:
        web:
          image: nginx:latest
          ports:
            - "80:80"
      networks:
        frontend: {}
    dest: /opt/app/docker-compose.yml
    owner: appuser
    group: appgroup
    mode: '0644'
    validate: true
"""

RETURN = r"""
dest:
    description: Path to the generated file
    type: str
    returned: always
content:
    description: The YAML content that was written
    type: str
    returned: always
"""

from ansible.module_utils.basic import AnsibleModule


class DockerComposeGen:
    def __init__(self, module):
        self.module = module
        self.compose = module.params["compose"]
        self.dest = module.params["dest"]
        self.mode = module.params["mode"]
        self.owner = module.params.get("owner")
        self.group = module.params.get("group")
        self.validate = module.params["validate"]
        self.tool = module.params.get("tool", "auto")

    def _resolve_uid(self, name):
        import pwd

        return pwd.getpwnam(name).pw_uid

    def _resolve_gid(self, name):
        import grp

        return grp.getgrnam(name).gr_gid

    def _file_hash(self, path):
        import hashlib

        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _validate_compose_file(self, content, tool):
        import os

        temp_path = os.path.join(self.module.tmpdir, "docker-compose.yml")
        with open(temp_path, "w") as temp_file:
            temp_file.write(content)

        try:
            if tool == "docker-compose":
                command = ["docker-compose", "-f", temp_path, "config"]
            elif tool == "compose-plugin":
                command = ["docker", "compose", "-f", temp_path, "config"]
            else:
                self.module.fail_json(msg=f"Unsupported tool: {tool}")

            rc, stdout, stderr = self.module.run_command(command)

            if rc != 0:
                self.module.fail_json(msg=f"Validation failed: {stderr}")
        except FileNotFoundError:
            self.module.fail_json(msg=f"{tool} is not installed or not in PATH.")
        except Exception as e:
            self.module.fail_json(msg=f"Unexpected error during validation: {e}")

    def _detect_tool(self):
        rc, stdout, stderr = self.module.run_command(
            ["docker", "compose", "version"], check_rc=True
        )
        if rc == 0:
            return "compose-plugin"

        rc, stdout, stderr = self.module.run_command(
            ["docker-compose", "--version"], check_rc=True
        )
        if rc == 0:
            return "docker-compose"

        return None

    def run(self):
        import os
        from ansible.module_utils.common.yaml import yaml_dump

        module = self.module
        compose = self.compose
        dest = self.dest
        mode = self.mode
        owner = self.owner
        group = self.group
        validate = self.validate
        tool = self.tool

        if tool == "auto":
            detected_tool = self._detect_tool()
            if not detected_tool:
                module.fail_json(
                    msg="Neither docker-compose nor compose plugin is available on the system."
                )
            tool = detected_tool

        module.debug(f"Using tool: {tool}")
        content = yaml_dump(compose, sort_keys=False, indent=2)

        if validate:
            self._validate_compose_file(content, tool)

        if module.check_mode:
            module.exit_json(changed=False, dest=dest, content=content)

        need_write = True
        if os.path.exists(dest):
            existing_hash = self._file_hash(dest)
            new_hash = __import__("hashlib").sha256(content.encode("utf-8")).hexdigest()
            if existing_hash == new_hash:
                need_write = False

        if not mode.isdigit() or not (0 <= int(mode, 8) <= 0o777):
            module.fail_json(msg=f"Invalid file mode: {mode}")

        if not os.access(os.path.dirname(dest), os.W_OK):
            module.fail_json(msg=f"Cannot write to directory: {os.path.dirname(dest)}")

        module.debug(f"Writing file to {dest}")
        module.debug(f"Setting mode to {mode}")
        module.debug(f"Setting owner to {owner} and group to {group}")

        if need_write:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w") as f:
                f.write(content)

        if owner or group:
            try:
                uid = self._resolve_uid(owner) if owner else -1
                gid = self._resolve_gid(group) if group else -1
                os.chown(dest, uid, gid)
            except KeyError as e:
                module.fail_json(msg=f"Failed to set ownership: {e}")
            except OSError as e:
                module.fail_json(msg=f"Failed to set ownership or permissions: {e}")
        try:
            os.chmod(dest, int(mode, 8))
        except OSError as e:
            module.fail_json(msg=f"Failed to set permissions: {e}")

        module.exit_json(changed=need_write, dest=dest, content=content)


def main():
    argument_spec = dict(
        compose=dict(type="dict", required=True),
        dest=dict(type="path", required=True),
        mode=dict(type="str", default="0644"),
        owner=dict(type="str"),
        group=dict(type="str"),
        validate=dict(type="bool", default=False),
        tool=dict(
            type="str",
            choices=["docker-compose", "compose-plugin", "auto"],
            default="auto",
        ),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    DockerComposeGen(module).run()


if __name__ == "__main__":
    main()
