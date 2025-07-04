class Figure:
    """Minimal Matplotlib Figure stub."""
    def __init__(self, figsize=(4, 2), dpi=100):
        self.figsize = figsize
        self.dpi = dpi
    def add_subplot(self, *args, **kwargs):
        return Subplot()

class Subplot:
    def set_title(self, *a, **k):
        pass
    def set_ylim(self, *a, **k):
        pass
    def set_xlim(self, *a, **k):
        pass
    def set_ylabel(self, *a, **k):
        pass
    def grid(self, *a, **k):
        pass
    def plot(self, *a, **k):
        return [Line()]
    def bar(self, *a, **k):
        return [Bar()]
    def cla(self):
        pass

class Line:
    def set_data(self, *a, **k):
        pass
    def set_color(self, *a, **k):
        pass

class Bar:
    def set_color(self, *a, **k):
        pass
