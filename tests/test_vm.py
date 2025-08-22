import src.utils.vm as vm
import scripts.run_vm_debug as vmcli


def test_launch_vm_debug_wrapper(monkeypatch):
    calls: list[str] = []

    def wrapper(port, open_code=False):
        calls.append("wrapper")
        return True

    def docker(port):
        calls.append("docker")
        return False

    def vagrant(port):
        calls.append("vagrant")
        return False

    def local(port):
        calls.append("local")

    monkeypatch.setattr(vm, "_launch_vm_debug_wrapper", wrapper)
    monkeypatch.setattr(vm, "_launch_docker", docker)
    monkeypatch.setattr(vm, "_launch_vagrant", vagrant)
    monkeypatch.setattr(vm, "_launch_local_debug", local)

    vm.launch_vm_debug()
    assert calls == ["wrapper"]


def test_launch_vm_debug_docker_windows(monkeypatch):
    cmds: list[list[str]] = []

    monkeypatch.setattr(vm, "_launch_vm_debug_wrapper", lambda p, open_code=False: False)
    monkeypatch.setattr(vm, "_is_windows", lambda: True)
    monkeypatch.setattr(vm, "_wsl_available", lambda: True)
    monkeypatch.setattr(vm, "_exists", lambda p: True)
    monkeypatch.setattr(vm, "_which", lambda name: "docker" if name == "docker" else None)

    def fake_spawn(cmd, **kwargs):
        cmds.append(list(cmd))

    monkeypatch.setattr(vm, "_spawn", fake_spawn)

    vm.launch_vm_debug(prefer="docker")
    assert cmds and cmds[0][0] == "wsl.exe"


def test_launch_vm_debug_vagrant(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(vm, "_launch_vm_debug_wrapper", lambda p, open_code=False: False)
    monkeypatch.setattr(vm, "_launch_docker", lambda p: calls.append("docker") or False)
    monkeypatch.setattr(vm, "_launch_vagrant", lambda p: calls.append("vagrant") or True)

    vm.launch_vm_debug()
    assert calls == ["docker", "vagrant"]


def test_launch_vm_debug_local_fallback(monkeypatch):
    cmds: list[list[str]] = []
    envs: list[dict[str, str]] = []

    monkeypatch.setattr(vm, "_launch_vm_debug_wrapper", lambda p, open_code=False: False)
    monkeypatch.setattr(vm, "_launch_docker", lambda p: False)
    monkeypatch.setattr(vm, "_launch_vagrant", lambda p: False)

    def fake_spawn(cmd, *, env=None, cwd=None):
        cmds.append(list(cmd))
        envs.append(dict(env or {}))

    monkeypatch.setattr(vm, "_spawn", fake_spawn)

    vm.launch_vm_debug(port=9999)
    assert any("debugpy" in part for part in cmds[0])
    assert envs[0]["DEBUG_PORT"] == "9999"


def test_vm_cli_parse_defaults():
    args = vmcli.parse_args([])
    assert args.prefer == "auto"
    assert args.code is False
    assert args.port == 5678
    assert args.list is False


def test_vm_cli_main_launch(monkeypatch):
    calls = []

    def fake_launch(prefer=None, open_code=False, port=5678, skip_deps=False):
        calls.append((prefer, open_code, port, skip_deps))

    monkeypatch.setattr(vmcli, "_load_launch", lambda: fake_launch)
    vmcli.main(["--prefer", "docker", "--code", "--port", "1234"])
    assert calls == [("docker", True, 1234, False)]


def test_vm_cli_main_list(monkeypatch, capsys):
    monkeypatch.setattr(vmcli, "available_backends", lambda: ["docker"])
    vmcli.main(["--list"])
    out = capsys.readouterr().out
    assert "docker" in out

