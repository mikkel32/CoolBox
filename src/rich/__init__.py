class Console:
    def print(self, *a, **k):
        pass

class Progress:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        pass

class SpinnerColumn:
    def __init__(self, *a, **k):
        pass

class TextColumn:
    def __init__(self, *a, **k):
        pass

class TimeElapsedColumn:
    pass
