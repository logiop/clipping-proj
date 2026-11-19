"""Thin wrapper around `claude -p` returning schema-validated structured output."""
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import jsonschema

TIMEOUT_S = 300


def _log(msg: str) -> None:
    print(f"claude: {msg}", file=sys.stderr)


def _extract(envelope: dict):
    """Structured output if present, else the JSON-parsed `result` string."""
    if envelope.get("structured_output") is not None:
        return envelope["structured_output"]
    result = envelope.get("result")
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return None
    return None


def ask(prompt: str, schema: dict, model: str, tools: str = "",
        add_dir: Optional[Path] = None, runner=subprocess.run) -> Optional[dict]:
    """Run one `claude -p` call; None on any failure or if the reply does not validate."""
    sendable = {k: v for k, v in schema.items() if k != "$schema"}
    argv = ["claude", "-p", "--tools", tools, "--output-format", "json",
            "--json-schema", json.dumps(sendable), "--model", model]
    if add_dir is not None:
        argv += ["--add-dir", str(add_dir)]
    try:
        proc = runner(argv, input=prompt, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        _log(f"timed out after {TIMEOUT_S}s")
        return None
    except OSError as exc:
        _log(f"cannot run claude: {exc}")
        return None
    if proc.returncode != 0:
        _log(f"exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}")
        return None
    try:
        envelope = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        _log("reply is not JSON")
        return None
    if not isinstance(envelope, dict) or envelope.get("is_error"):
        _log("error reply")
        return None
    data = _extract(envelope)
    if not isinstance(data, dict):
        _log("no structured output")
        return None
    try:
        jsonschema.validate(data, sendable)
    except jsonschema.ValidationError as exc:
        _log(f"schema validation failed: {exc.message[:200]}")
        return None
    return data
