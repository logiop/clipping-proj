from pathlib import Path

from clipping.listen import chat

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_live_chat_offsets():
    lines = (FIXTURES / "live_chat.json").read_text().splitlines()
    assert chat.parse_live_chat(lines) == [5.0, 12.0]


def test_rate_buckets():
    assert chat.rate([1.0, 4.9, 5.0, 12.0], bucket=5) == {0: 2, 5: 1, 10: 1}


def test_bursts_relative_to_median():
    rate = {i * 5: 2 for i in range(10)}
    rate[25] = 20
    result = chat.bursts(rate)
    assert result == [(25, 10.0)]


def test_bursts_empty():
    assert chat.bursts({}) == []
