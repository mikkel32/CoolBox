import builtins
import scripts.exe_tester_vm_debug as evd


def test_parse_defaults():
    args = evd.parse_args(['foo.exe'])
    assert args.prefer == 'auto'
    assert args.code is False
    assert args.port == 5678
    assert args.skip_deps is False
    assert args.quiet is False
    assert args.no_wait is False
    assert args.detach is False


def test_main_passes_args(monkeypatch):
    called = {}

    def fake_launch(prefer=None, open_code=False, port=5678, skip_deps=False, target=None, print_output=True, nowait=False, detach=False):
        called['prefer'] = prefer
        called['open_code'] = open_code
        called['port'] = port
        called['skip_deps'] = skip_deps
        called['target'] = target
        called['print_output'] = print_output
        called['nowait'] = nowait
        called['detach'] = detach
        return True

    monkeypatch.setattr(evd, 'launch_vm_debug', fake_launch)
    monkeypatch.setattr(evd, 'pick_port', lambda p: 6000)
    evd.main(['--prefer', 'docker', '--code', '--port', '5000', '--skip-deps', '--no-wait', '--quiet', '--detach', 'test.exe', '--', '--iterations', '2'])
    assert called['prefer'] == 'docker'
    assert called['open_code'] is True
    assert called['port'] == 6000
    assert called['skip_deps'] is True
    assert called['print_output'] is False
    assert called['nowait'] is True
    assert called['detach'] is True
    assert 'test.exe' in called['target']
