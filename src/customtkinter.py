class CTkBaseClass:
    def __init__(self, *a, **k):
        self._children = []
        self._exists = True
    def destroy(self):
        self._exists = False
    def update_idletasks(self):
        pass
    def update(self):
        pass
    def winfo_children(self):
        return list(self._children)
    def winfo_exists(self):
        return 1 if self._exists else 0
    def pack(self, *a, **k):
        pass
    def grid(self, *a, **k):
        pass
    def configure(self, **k):
        pass

class CTk(CTkBaseClass):
    pass

class CTkToplevel(CTkBaseClass):
    pass

class CTkFrame(CTkBaseClass):
    pass

class CTkButton(CTkBaseClass):
    pass

class CTkLabel(CTkBaseClass):
    pass

class CTkEntry(CTkBaseClass):
    pass

class CTkSwitch(CTkBaseClass):
    pass

class CTkProgressBar(CTkBaseClass):
    pass

class CTkOptionMenu(CTkBaseClass):
    pass

class CTkSegmentedButton(CTkBaseClass):
    pass

class CTkTabview(CTkBaseClass):
    pass

class CTkScrollableFrame(CTkBaseClass):
    pass

class CTkCheckBox(CTkBaseClass):
    pass

class CTkSlider(CTkBaseClass):
    pass

class CTkTextbox(CTkBaseClass):
    pass

class CTkFont:
    def __init__(self, *a, **k):
        pass

class StringVar:
    def __init__(self, value=""):
        self._value = value
    def get(self):
        return self._value
    def set(self, value):
        self._value = value

class IntVar(StringVar):
    def __init__(self, value=0):
        super().__init__(value)

class DoubleVar(StringVar):
    def __init__(self, value=0.0):
        super().__init__(value)

class BooleanVar(StringVar):
    def __init__(self, value=False):
        super().__init__(value)

__all__ = [name for name in globals() if name.startswith('CTk') or name.endswith('Var')]
