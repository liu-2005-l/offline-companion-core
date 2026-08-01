import ctypes
import os
import sys
from pathlib import Path

base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent / '_internal')) / 'llama_cpp' / 'lib'
print('base', base, base.exists())
os.add_dll_directory(str(base))
os.environ['PATH'] = str(base) + os.pathsep + os.environ.get('PATH', '')
for name in ('ggml-base.dll', 'ggml-cpu.dll', 'ggml.dll', 'llama.dll'):
    path = base / name
    print('preload', name, path.exists(), path.stat().st_size if path.exists() else None)
    ctypes.WinDLL(str(path))
import llama_cpp
print('import ok')
llama_cpp.llama_backend_init()
print('backend init ok')
