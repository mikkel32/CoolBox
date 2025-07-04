class DummyTkWidget:
    def __init__(self):
        self._exists = True
    def winfo_exists(self):
        return 1 if self._exists else 0
    def pack(self, *a, **k):
        pass

class FigureCanvasTkAgg:
    def __init__(self, figure, master=None):
        self.figure = figure
        self._widget = DummyTkWidget()
    def draw(self):
        pass
    def draw_idle(self):
        pass
    def get_tk_widget(self):
        return self._widget

class NavigationToolbar2Tk:
    def __init__(self, canvas, window):
        self.canvas = canvas
        self.window = window
        self._widget = DummyTkWidget()
    def update(self):
        pass
    def pack(self, *a, **k):
        self._widget.pack(*a, **k)
