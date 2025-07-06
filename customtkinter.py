from importlib import import_module
module = import_module('src.customtkinter')
for name in getattr(module, '__all__', dir(module)):
    globals()[name] = getattr(module, name)
__all__ = getattr(module, '__all__', [n for n in globals() if not n.startswith('_')])
