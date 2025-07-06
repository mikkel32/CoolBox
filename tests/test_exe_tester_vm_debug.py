import builtins
import scripts.exe_tester_vm_debug as evd


def test_parse_defaults():
    args = evd.parse_args(['foo.exe'])
    assert args.prefer == 'auto'
    assert args.code is False
    assert args.port == 5678
    assert args.skip_deps is False


def test_main_passes_args(monkeypatch):
    called = {}

    def fake_launch(prefer=None, open_code=False, port=5678, skip_deps=False, target=None):
        called['prefer'] = prefer
        called['open_code'] = open_code
        called['port'] = port
        called['skip_deps'] = skip_deps
        called['target'] = target

    monkeypatch.setattr(evd, 'launch_vm_debug', fake_launch)
    monkeypatch.setattr(evd, 'pick_port', lambda p: 6000)
    evd.main(['--prefer', 'docker', '--code', '--port', '5000', '--skip-deps', 'test.exe', '--', '--iterations', '2'])
    assert called['prefer'] == 'docker'
    assert called['open_code'] is True
    assert called['port'] == 6000
    assert called['skip_deps'] is True
    assert 'test.exe' in called['target']
