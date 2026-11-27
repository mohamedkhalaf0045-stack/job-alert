import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gap_monitor import _merge_handled  # noqa: E402


def test_current_findings_always_kept_even_if_old():
    handled = {str(4480000000 + i) for i in range(600)}
    old_current = {"4470659508"}
    out = _merge_handled(handled, old_current, cap=500)
    assert "4470659508" in out
    assert len(out) == 500


def test_newest_old_ids_kept_and_order_numeric():
    handled = {"999", "1000", "4470659508"}
    out = _merge_handled(handled, set(), cap=2)
    assert out == ["1000", "4470659508"]


def test_under_cap_keeps_everything():
    out = _merge_handled({"1", "2"}, {"3"}, cap=10)
    assert out == ["1", "2", "3"]
