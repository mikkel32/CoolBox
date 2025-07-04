class Console:
    def print(self, *a, **k):
        pass
    def log(self, *a, **k):
        pass

class Control:
    def __init__(self, *a, **k):
        pass

class Group:
    def __init__(self, *a, **k):
        self.renderables = list(a)
__all__ = ['Console','Control','Group']
