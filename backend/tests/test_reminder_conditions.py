from __future__ import annotations

import pytest

from app.application.reminder_conditions import evaluate_condition, normalize_output, path_segments
from app.domain.reminders import ResultCondition


def test_tool_json_strings_are_normalized_and_selected_by_id():
    output = normalize_output(
        {
            "items": '[{"id":41,"status":"SUCCESS/ALL"},{"id":42,"status":"DOWNLOADING"}]',
            "status": '{"remaining_mb":0,"paused":false}',
        }
    )
    condition = ResultCondition(path="items[id=42].status", operator="contains", value="SUCCESS")
    assert not evaluate_condition(output, condition).matched
    output["items"][1]["status"] = "SUCCESS/ALL"
    assert evaluate_condition(output, condition).matched
    assert evaluate_condition(output, ResultCondition(path="status.remaining_mb", value=0)).matched
    assert not evaluate_condition(output, ResultCondition(path="status.paused", value=0)).matched


@pytest.mark.parametrize(
    "path,operator,value,expected",
    [
        ("items[*].status", "contains", "SUCCESS", True),
        ("items.0.status", "equals", "SUCCESS/ALL", True),
        ('items[id="a.b"].status', "exists", None, True),
        ("items[id=99].status", "not_equals", "SUCCESS", False),
        ("items[id=99].status", "not_exists", None, True),
        ("status.remaining_mb", "lte", 5, True),
        ("status.remaining_mb", "gt", 5, False),
        ("empty", "is_empty", None, True),
    ],
)
def test_declarative_condition_paths_and_missing_values(path, operator, value, expected):
    output = {
        "items": [{"id": "a.b", "status": "SUCCESS/ALL"}],
        "status": {"remaining_mb": 3},
        "empty": [],
    }
    result = evaluate_condition(output, ResultCondition(path=path, operator=operator, value=value))
    assert result.matched is expected


def test_changed_requires_a_baseline_and_retains_stable_json_order():
    condition = ResultCondition(path="status", operator="changed")
    first = evaluate_condition({"status": {"a": 1, "b": 2}}, condition)
    assert not first.matched
    assert not evaluate_condition(
        {"status": {"b": 2, "a": 1}}, condition, first.fingerprint
    ).matched
    assert evaluate_condition({"status": {"b": 3, "a": 1}}, condition, first.fingerprint).matched


@pytest.mark.parametrize(
    "path", ["a..b", "items[", "a[0][1]", "__import__('os')", "items[?(@.id==1)]"]
)
def test_paths_are_validated_without_executing_expressions(path):
    with pytest.raises(ValueError):
        path_segments(path)


@pytest.mark.parametrize("index", ["²", "①"])
def test_non_decimal_numeric_indices_are_rejected_before_evaluation(index):
    with pytest.raises(ValueError, match="Usa una ruta"):
        path_segments(f"items.{index}.status")


@pytest.mark.parametrize("index", ["0", "٠"])
def test_decimal_indices_select_list_items(index):
    result = evaluate_condition(
        {"items": [{"status": "ready"}]},
        ResultCondition(path=f"items.{index}.status", value="ready"),
    )
    assert result.matched
