from time import sleep

from coolbox.utils.thread_manager import ThreadManager


def test_thread_manager_threads_and_communication():
    tm = ThreadManager()
    tm.start()
    for _ in range(5):
        tm.cmd_queue.put("work")
        tm.log_queue.put("msg")
    sleep(0.5)
    tm.stop()
    assert any(log == "msg" for log in tm.logs)
    assert not any("stalled" in log for log in tm.logs)


def test_thread_manager_detects_contention():
    tm = ThreadManager()
    tm.start()
    tm.lock.acquire()
    sleep(1.2)
    tm.lock.release()
    sleep(0.5)
    tm.stop()
    assert any("lock contention" in log for log in tm.logs)
