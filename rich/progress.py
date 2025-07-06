class Progress:
    def __init__(self, *a, console=None, **k):
        self.console = console
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        pass
    def add_task(self, *a, **k):
        return 0
class SpinnerColumn:
    def __init__(self, *a, **k):
        pass
class TextColumn:
    def __init__(self, *a, **k):
        pass
class TimeElapsedColumn:
    pass
class BarColumn:
    def __init__(self, *a, **k):
        pass
__all__ = ['Progress','SpinnerColumn','TextColumn','TimeElapsedColumn','BarColumn']
