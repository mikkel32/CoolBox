from coolbox.utils.thread_manager import ThreadManager


def test_post_exception_falls_back_when_after_fails():
    manager = ThreadManager()

    called = {}

    class DummyWindow:
        def after(self, *_args, **_kw):
            raise RuntimeError("after failed")

        def report_callback_exception(self, exc_type, exc, tb):
            called['args'] = (exc_type, exc, tb)

    window = DummyWindow()

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        manager.post_exception(window, exc)

    assert 'args' in called
    exc_type, exc_value, tb = called['args']
    assert exc_type is RuntimeError
    assert isinstance(exc_value, RuntimeError)
    assert tb is not None
