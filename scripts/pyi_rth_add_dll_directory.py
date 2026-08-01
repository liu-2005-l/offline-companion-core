"""PyInstaller runtime hook: Add llama_cpp DLL directory to search path."""

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # In frozen mode, add _internal and _internal/llama_cpp/lib to DLL search path
    internal_dir = Path(sys.executable).parent / "_internal"
    if internal_dir.exists():
        # Add to PATH for maximum compatibility
        os.environ["PATH"] = str(internal_dir) + os.pathsep + os.environ.get("PATH", "")
        llama_lib_dir = internal_dir / "llama_cpp" / "lib"
        if llama_lib_dir.exists():
            os.environ["PATH"] = str(llama_lib_dir) + os.pathsep + os.environ.get("PATH", "")
