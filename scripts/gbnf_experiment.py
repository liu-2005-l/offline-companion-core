"""执行本地 llama-server GBNF 工具选择实验（B4）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from offline_companion.core.gbnf import tool_schema_to_gbnf


@dataclass(frozen=True)
class Case:
    prompt: str
    expected: str


CASES = tuple(
    [Case("调用时间工具", "datetime_now")] * 7
    + [Case("不要调用工具，直接回答", "none")] * 7
    + [Case("调用时间工具但缺少参数", "datetime_now")] * 6
)


def main() -> int:
    parser = argparse.ArgumentParser(description="B4 GBNF sidecar sampling")
    parser.add_argument("--url", default=os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    grammar = tool_schema_to_gbnf(
        [
            {
                "tool_id": "datetime_now",
                "params_schema": {"type": "object", "properties": {}, "required": []},
            }
        ]
    )
    if args.dry_run:
        print(json.dumps({"cases": len(CASES), "grammar": grammar}, ensure_ascii=False, indent=2))
        return 0
    results = [_sample(args.url, case, grammar) for case in CASES]
    completed = [item for item in results if item["status"] == "completed"]
    valid = [item for item in completed if item["valid"]]
    report = {
        "cases": len(CASES),
        "completed": len(completed),
        "valid": len(valid),
        "valid_rate": len(valid) / len(CASES),
        "decision": "立项候选" if len(valid) / len(CASES) >= 0.8 else "关闭入档",
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if len(completed) == len(CASES) else 2


def _sample(url: str, case: Case, grammar: str) -> dict[str, object]:
    payload = {
        "model": "local",
        "messages": [{"role": "user", "content": case.prompt}],
        "max_tokens": 80,
        "stream": False,
        "grammar": grammar,
    }
    request = Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = str(body["choices"][0]["message"]["content"])
        parsed = json.loads(content)
        valid = parsed.get("name") in {"datetime_now", "none"} and isinstance(parsed.get("parameters"), dict)
        return {"prompt": case.prompt, "status": "completed", "valid": valid, "output": parsed}
    except (OSError, URLError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"prompt": case.prompt, "status": "blocked", "valid": False, "error": str(exc)}


if __name__ == "__main__":
    raise SystemExit(main())
