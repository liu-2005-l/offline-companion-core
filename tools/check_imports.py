"""check_imports：最小分层与危险导入检查。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "offline_companion"
FORBIDDEN = ("exec(", "eval(", "urllib.request.urlopen", "socket.socket", "importlib.import_module")


def main() -> int:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in FORBIDDEN):
            offenders.append(str(path))
    if offenders:
        print("发现受限实现，请人工复核：")
        for item in offenders:
            print(item)
        return 1
    print("check_imports: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
