import os
import pytest
from ansible_collections.bdclark.home_automation.plugins.modules.docker_compose_gen import (
    DockerComposeGen,
)


class DummyModule:
    def __init__(self, params):
        self.params = params
        self.check_mode = False
        self.tmpdir = "/tmp"
        self.debug_msgs = []
        self.failed = False
        self.failed_msg = None
        self.exited = False
        self.exit_args = None

    def fail_json(self, **kwargs):
        self.failed = True
        self.failed_msg = kwargs.get("msg", "fail_json called")
        raise Exception(self.failed_msg)

    def exit_json(self, **kwargs):
        self.exited = True
        self.exit_args = kwargs
        raise SystemExit()

    def debug(self, msg):
        self.debug_msgs.append(msg)

    def run_command(self, command, check_rc=True):
        # Simulate docker-compose config always passing
        if "docker-compose" in command or "docker" in command:
            return (0, "ok", "")
        return (1, "", "fail")


@pytest.fixture
def compose_dict():
    return {
        "version": "3.9",
        "services": {"web": {"image": "nginx:latest", "ports": ["80:80"]}},
        "networks": {"frontend": {}},
    }


def test_successful_write(tmp_path, compose_dict):
    dest = str(tmp_path / "docker-compose.yml")
    params = {
        "compose": compose_dict,
        "dest": dest,
        "mode": "0644",
        "validate": False,
        "tool": "auto",
    }
    module = DummyModule(params)
    gen = DockerComposeGen(module)
    # Patch file_hash to always return different hash
    gen._file_hash = lambda path: "oldhash"
    # Patch resolve_uid/gid to avoid system calls
    gen._resolve_uid = lambda name: os.getuid()
    gen._resolve_gid = lambda name: os.getgid()
    # Patch os.chown and os.chmod
    os.chown = lambda *a, **kw: None
    os.chmod = lambda *a, **kw: None
    # Patch os.access to always True
    os.access = lambda *a, **kw: True
    # Patch os.makedirs
    os.makedirs = lambda *a, **kw: None
    # Patch os.path.exists to False to force write
    os.path.exists = lambda path: False
    # Patch open to write to a temp file
    open_file = tmp_path / "docker-compose.yml"

    def fake_open(path, mode):
        return open(open_file, mode)

    gen.open = fake_open
    # Actually run
    try:
        gen.run()
    except SystemExit:
        pass
    assert module.exited
    assert module.exit_args["changed"] is True
    assert module.exit_args["dest"] == dest
    assert "version" in module.exit_args["content"]
    assert "services" in module.exit_args["content"]
    assert "networks" in module.exit_args["content"]


def test_invalid_mode(compose_dict):
    params = {
        "compose": compose_dict,
        "dest": "/tmp/docker-compose.yml",
        "mode": "invalid",
        "validate": False,
        "tool": "auto",
    }
    module = DummyModule(params)
    gen = DockerComposeGen(module)
    # Patch os.access to always True
    os.access = lambda *a, **kw: True
    # Patch os.path.exists to False
    os.path.exists = lambda path: False
    with pytest.raises(Exception) as exc:
        gen.run()
    assert "Invalid file mode" in str(exc.value)


def test_fail_on_unwritable_dir(compose_dict):
    params = {
        "compose": compose_dict,
        "dest": "/tmp/docker-compose.yml",
        "mode": "0644",
        "validate": False,
        "tool": "auto",
    }
    module = DummyModule(params)
    gen = DockerComposeGen(module)
    # Patch os.access to always False
    os.access = lambda *a, **kw: False
    # Patch os.path.exists to False
    os.path.exists = lambda path: False
    with pytest.raises(Exception) as exc:
        gen.run()
    assert "Cannot write to directory" in str(exc.value)


def test_check_mode(compose_dict):
    params = {
        "compose": compose_dict,
        "dest": "/tmp/docker-compose.yml",
        "mode": "0644",
        "validate": False,
        "tool": "auto",
    }
    module = DummyModule(params)
    module.check_mode = True
    gen = DockerComposeGen(module)
    # Patch os.access to always True
    os.access = lambda *a, **kw: True
    # Patch os.path.exists to False
    os.path.exists = lambda path: False
    try:
        gen.run()
    except SystemExit:
        pass
    assert module.exited
    assert module.exit_args["changed"] is False
    assert "content" in module.exit_args
