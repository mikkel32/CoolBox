import sys
from importlib import import_module, util

module = None
try:
    sys.modules.pop('psutil', None)
    path0 = sys.path.pop(0)
    module = import_module('psutil')
    sys.path.insert(0, path0)
    if getattr(module, '__file__', '') == __file__:
        module = None
except Exception:
    sys.path.insert(0, path0)
    module = None

if module is None:
    module = import_module('src.psutil')

for name in getattr(module, '__all__', dir(module)):
    globals()[name] = getattr(module, name)

__all__ = getattr(module, '__all__', [n for n in globals() if not n.startswith('_')])
