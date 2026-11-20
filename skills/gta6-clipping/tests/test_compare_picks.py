import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compare_picks  # noqa: E402


def test_overlap_half():
    assert compare_picks.overlap((0, 30), (15, 45)) == 0.5
    assert compare_picks.overlap((0, 10), (20, 30)) == 0.0


def test_match_picks_best_overlap():
    new = [{"start": 100, "end": 130}, {"start": 900, "end": 930}]
    old = [{"file": "03.mp4", "start": 90, "end": 125}, {"file": "04.mp4", "start": 110, "end": 140}]
    pairs = compare_picks.match(new, old)
    assert pairs[0][1]["file"] == "03.mp4" and pairs[1][1] is None  # 25 s shared vs 20 s


def test_compare_missing_baseline_is_clear(tmp_path, capsys):
    new = tmp_path / "compare_1.json"
    new.write_text(json.dumps({"moments": [{"start": 1, "end": 31}]}))
    assert compare_picks.main([str(new), str(tmp_path / "nope.json")]) == 2
    err = capsys.readouterr().err
    assert "nope.json" in err and "Traceback" not in err


def test_compare_prints_table_and_matches(tmp_path, capsys):
    new = tmp_path / "compare_1.json"
    new.write_text(json.dumps({"moments": [{"start": 100, "end": 130, "score": 80, "event": "funny_fail",
                                            "hook": "new hook"}]}))
    old = tmp_path / "clips_1.json"
    old.write_text(json.dumps([{"file": "03.mp4", "start": 105, "end": 135, "hook": "old hook"}]))
    assert compare_picks.main([str(new), str(old)]) == 0
    out = capsys.readouterr().out
    assert "03.mp4" in out and "new hook" in out and "matches: 1/1" in out
