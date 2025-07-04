from importlib import import_module, machinery, util
import sys
from pathlib import Path

module = None
root = str(Path(__file__).resolve().parent)
paths = [p for p in sys.path if Path(p).resolve() != Path(root).resolve()]
previous = sys.modules.pop('psutil', None)
spec = machinery.PathFinder().find_spec('psutil', paths)
if spec and getattr(spec, 'origin', None) != __file__:
    module = util.module_from_spec(spec)
    sys.modules['psutil'] = module
    spec.loader.exec_module(module)
else:
    if previous is not None:
        sys.modules['psutil'] = previous
    module = import_module('src.psutil')

for name in getattr(module, '__all__', dir(module)):
    globals()[name] = getattr(module, name)

__all__ = getattr(module, '__all__', [n for n in globals() if not n.startswith('_')])
