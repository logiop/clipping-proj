"""Thin wrapper around `claude -p` returning schema-validated structured output."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

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


def build_argv(sendable: dict, model: str, tools: str, read_dir: Optional[Path]) -> List[str]:
    """The sealed `claude -p` command line.

    --strict-mcp-config drops every MCP server of the user's config; dontAsk denies anything
    not explicitly allowed. Tools (Read only, for the visual check) are allowed only inside
    `read_dir` (`//abs/**` is the absolute-path rule syntax): a bare `Read` allow rule was
    verified to approve reads anywhere on disk.
    """
    argv = ["claude", "-p", "--tools", tools, "--strict-mcp-config", "--permission-mode", "dontAsk"]
    if read_dir is not None:
        argv += ["--add-dir", str(read_dir)]
        argv += ["--allowedTools", ",".join(f"{t.strip()}(/{read_dir}/**)" for t in tools.split(","))]
    return argv + ["--output-format", "json", "--json-schema", json.dumps(sendable),
                   "--model", model, "--no-session-persistence"]


def _run(argv: List[str], prompt: str, read_dir: Optional[Path], runner):
    """Run in `read_dir`, or in a fresh empty temp dir so the user's cwd is never inherited."""
    if read_dir is not None:
        return runner(argv, input=prompt, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=str(read_dir))
    with tempfile.TemporaryDirectory(prefix="gta6clip-claude-") as empty:
        return runner(argv, input=prompt, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=empty)


def ask(prompt: str, schema: dict, model: str, tools: str = "",
        add_dir: Optional[Path] = None, runner=subprocess.run) -> Optional[dict]:
    """Run one `claude -p` call; None on any failure or if the reply does not validate.

    ValueError when tools are requested without `add_dir` (no tool may run unscoped).
    """
    if tools and add_dir is None:
        raise ValueError("tools need add_dir: they are only allowed inside that directory")
    sendable = {k: v for k, v in schema.items() if k != "$schema"}
    read_dir = Path(add_dir).resolve() if add_dir is not None else None
    argv = build_argv(sendable, model, tools, read_dir)
    try:
        proc = _run(argv, prompt, read_dir, runner)
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
