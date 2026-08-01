# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['_tmp_llama_init_probe.py'],
    pathex=['.\\.venv\\Lib\\site-packages'],
    binaries=[('E:\\Python\\offline-companion-core\\.venv\\Lib\\site-packages\\llama_cpp\\lib\\llama.dll', 'llama_cpp\\lib'), ('E:\\Python\\offline-companion-core\\.venv\\Lib\\site-packages\\llama_cpp\\lib\\ggml.dll', 'llama_cpp\\lib'), ('E:\\Python\\offline-companion-core\\.venv\\Lib\\site-packages\\llama_cpp\\lib\\ggml-base.dll', 'llama_cpp\\lib'), ('E:\\Python\\offline-companion-core\\.venv\\Lib\\site-packages\\llama_cpp\\lib\\ggml-cpu.dll', 'llama_cpp\\lib'), ('E:\\Python\\offline-companion-core\\.venv\\Lib\\site-packages\\llama_cpp\\lib\\mtmd.dll', 'llama_cpp\\lib')],
    datas=[],
    hiddenimports=['llama_cpp', 'llama_cpp.llama_cpp'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LlamaManualProbe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LlamaManualProbe',
)
