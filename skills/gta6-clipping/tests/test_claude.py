import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipping import claude

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "required": ["n"],
    "properties": {"n": {"type": "integer"}},
}


def fake(stdout="", returncode=0, calls=None):
    def runner(argv, **kw):
        if calls is not None:
            calls.append((argv, kw))
        return SimpleNamespace(stdout=stdout, returncode=returncode, stderr="boom")
    return runner


def envelope(**kw):
    return json.dumps({"is_error": False, **kw})


def test_ask_passes_no_tools():
    calls = []
    claude.ask("hi", SCHEMA, "sonnet", runner=fake(envelope(structured_output={"n": 1}), calls=calls))
    argv, kw = calls[0]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert kw["input"] == "hi" and kw["timeout"] == 300
    assert "--add-dir" not in argv
    assert "--no-session-persistence" in argv


def test_ask_strips_dollar_schema_and_adds_dir(tmp_path):
    calls = []
    claude.ask("hi", SCHEMA, "m", tools="Read", add_dir=tmp_path,
               runner=fake(envelope(structured_output={"n": 1}), calls=calls))
    argv, _ = calls[0]
    sent = json.loads(argv[argv.index("--json-schema") + 1])
    assert "$schema" not in sent and sent["required"] == ["n"]
    assert argv[argv.index("--add-dir") + 1] == str(tmp_path)
    assert argv[argv.index("--tools") + 1] == "Read"


def test_ask_is_sealed_from_user_mcp_and_permissions():
    calls = []
    claude.ask("hi", SCHEMA, "m", runner=fake(envelope(structured_output={"n": 1}), calls=calls))
    argv, _ = calls[0]
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--allowedTools" not in argv


def test_ask_without_tools_runs_in_a_fresh_empty_dir():
    calls, seen = [], {}

    def runner(argv, **kw):
        seen["cwd"] = kw["cwd"]
        seen["listing"] = list(Path(kw["cwd"]).iterdir())
        return fake(envelope(structured_output={"n": 1}), calls=calls)(argv, **kw)

    claude.ask("hi", SCHEMA, "m", runner=runner)
    assert seen["listing"] == []
    assert Path(seen["cwd"]).resolve() != Path.cwd().resolve()
    assert not Path(seen["cwd"]).exists()  # removed after the call


def test_ask_with_read_is_scoped_to_the_add_dir(tmp_path):
    calls = []
    claude.ask("hi", SCHEMA, "m", tools="Read", add_dir=tmp_path,
               runner=fake(envelope(structured_output={"n": 1}), calls=calls))
    argv, kw = calls[0]
    assert argv[argv.index("--allowedTools") + 1] == f"Read(/{tmp_path.resolve()}/**)"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--strict-mcp-config" in argv
    assert kw["cwd"] == str(tmp_path.resolve())


def test_ask_refuses_tools_without_a_dir():
    with pytest.raises(ValueError):
        claude.ask("hi", SCHEMA, "m", tools="Read", runner=fake(envelope(structured_output={"n": 1})))


def test_ask_returns_structured_output():
    assert claude.ask("p", SCHEMA, "m", runner=fake(envelope(structured_output={"n": 3}))) == {"n": 3}


def test_ask_falls_back_to_result_string():
    assert claude.ask("p", SCHEMA, "m", runner=fake(envelope(result='{"n": 4}'))) == {"n": 4}


def test_ask_none_on_nonzero_exit():
    assert claude.ask("p", SCHEMA, "m", runner=fake("", returncode=1)) is None


def test_ask_none_on_timeout():
    def runner(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 300)
    assert claude.ask("p", SCHEMA, "m", runner=runner) is None


def test_ask_none_on_missing_binary():
    def runner(argv, **kw):
        raise FileNotFoundError("claude")
    assert claude.ask("p", SCHEMA, "m", runner=runner) is None


def test_ask_none_on_garbage():
    assert claude.ask("p", SCHEMA, "m", runner=fake("not json")) is None


def test_ask_none_on_schema_failure():
    assert claude.ask("p", SCHEMA, "m", runner=fake(envelope(structured_output={"n": "x"}))) is None


def test_ask_none_on_error_envelope():
    out = json.dumps({"is_error": True, "result": '{"n": 1}'})
    assert claude.ask("p", SCHEMA, "m", runner=fake(out)) is None


def test_ask_none_when_no_output():
    assert claude.ask("p", SCHEMA, "m", runner=fake(envelope(result="plain text"))) is None


# --- token budget (lean context + usage meter) ---

def _flag_value(argv, flag):
    return argv[argv.index(flag) + 1]


def test_ask_runs_without_user_settings_and_with_short_system_prompt():
    calls = []
    claude.ask("p", SCHEMA, "sonnet", runner=fake(envelope(structured_output={"n": 1}), calls=calls))
    argv = calls[0][0]
    assert _flag_value(argv, "--setting-sources") == ""
    assert _flag_value(argv, "--system-prompt") == claude.SYSTEM_PROMPT
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--json-schema"):
        assert flag in argv
    assert _flag_value(argv, "--permission-mode") == "dontAsk"


def test_usage_from_envelope():
    env = {"usage": {"input_tokens": 2, "cache_creation_input_tokens": 14129,
                     "cache_read_input_tokens": 649, "output_tokens": 4},
           "total_cost_usd": 0.0028}
    u = claude.usage_from(env)
    assert u == claude.Usage(2, 14129, 649, 4, 0.0028, 1)
    assert u.total_tokens == 14784


def test_meter_ignores_missing_usage():
    meter = claude.UsageMeter()
    meter.add(claude.usage_from({}))
    total = meter.total()
    assert total.total_tokens == 0 and total.cost_usd == 0.0 and total.calls == 1


def test_meter_is_thread_safe():
    import threading
    meter = claude.UsageMeter()

    def work():
        for _ in range(100):
            meter.add(claude.Usage(input=1, calls=1))

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert meter.total().input == 800 and meter.total().calls == 800


def test_usage_recorded_even_when_schema_fails():
    meter = claude.UsageMeter()
    out = envelope(structured_output={"n": "not-int"}, usage={"input_tokens": 5, "output_tokens": 1})
    assert claude.ask("p", SCHEMA, "sonnet", runner=fake(out), meter=meter) is None
    assert meter.total().calls == 1 and meter.total().input == 5
