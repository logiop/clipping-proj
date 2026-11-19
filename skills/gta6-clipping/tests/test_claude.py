import json
import subprocess
from types import SimpleNamespace

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


def test_ask_strips_dollar_schema_and_adds_dir(tmp_path):
    calls = []
    claude.ask("hi", SCHEMA, "m", tools="Read", add_dir=tmp_path,
               runner=fake(envelope(structured_output={"n": 1}), calls=calls))
    argv, _ = calls[0]
    sent = json.loads(argv[argv.index("--json-schema") + 1])
    assert "$schema" not in sent and sent["required"] == ["n"]
    assert argv[argv.index("--add-dir") + 1] == str(tmp_path)
    assert argv[argv.index("--tools") + 1] == "Read"


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
