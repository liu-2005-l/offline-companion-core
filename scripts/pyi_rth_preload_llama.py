"""PyInstaller runtime hook：提前加载并预检 llama_cpp C 后端。"""

try:
    import llama_cpp

    llama_cpp.llama_backend_init()
    print("[RTH] llama_cpp backend init ok")
except ImportError as exc:
    print(f"[RTH] llama_cpp import failed: {exc}")
except OSError as exc:
    print(f"[RTH] llama_cpp backend init failed: {type(exc).__name__}: {exc}")
