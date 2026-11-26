"""Tests for dcode_diff (pure module, loaded by path so no Home Assistant is needed)."""
import importlib.util
from pathlib import Path

_PATH = Path(__file__).parents[1] / "custom_components" / "philips_airplus" / "dcode_diff.py"
_spec = importlib.util.spec_from_file_location("dcode_diff", _PATH)
dcode_diff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dcode_diff)


def test_detects_changed_value():
    old = {"D0310D": 6, "D0320F": 0}
    new = {"D0310D": 7, "D0320F": 0}
    assert dcode_diff.diff_reported(old, new) == [("D0310D", 6, 7)]


def test_new_and_removed_keys():
    assert dcode_diff.diff_reported({"A": 1}, {"B": 2}) == [("A", 1, None), ("B", None, 2)]


def test_noisy_keys_ignored():
    old = {"Runtime": 1, "rssi": -50, "free_memory": 1, "D03102": 0}
    new = {"Runtime": 2, "rssi": -51, "free_memory": 2, "D03102": 1}
    assert dcode_diff.diff_reported(old, new) == [("D03102", 0, 1)]


def test_d03105_is_logged():
    # candidate for the CX7550 display setting, must not be filtered
    assert dcode_diff.diff_reported({"D03105": 115}, {"D03105": 0}) == [("D03105", 115, 0)]


def test_none_inputs():
    assert dcode_diff.diff_reported(None, None) == []
    assert dcode_diff.diff_reported(None, {"X": 1}) == [("X", None, 1)]


def test_sorted_output():
    changes = dcode_diff.diff_reported({}, {"D2": 1, "D1": 1})
    assert [key for key, _, _ in changes] == ["D1", "D2"]


def test_format_changes():
    text = dcode_diff.format_changes([("D0310D", 6, 7), ("D01S05", None, "CX7550/01")])
    assert text == "D0310D: 6 -> 7, D01S05: None -> 'CX7550/01'"


def test_format_redacts_identifying_keys():
    text = dcode_diff.format_changes([("DeviceId", None, "abc123"), ("D01S03", None, "Wohnzimmer")])
    assert "abc123" not in text
    assert "Wohnzimmer" not in text
    assert text == "DeviceId: ***, D01S03: ***"
