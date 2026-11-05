from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

from pydantic import JsonValue

from app.domain.reminders import ResultCondition

_TOKEN = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_-]*)(?:\[(\*|\d+|[a-zA-Z_][a-zA-Z0-9_-]*=[^\[\]]{1,128})\])?$"
)


@dataclass(frozen=True)
class ConditionResult:
    matched: bool
    values: list[JsonValue]
    fingerprint: str
    preview: str


def path_segments(path: str) -> list[str]:
    if path == "$":
        return []
    if path.startswith("$."):
        path = path[2:]
    segments, current, depth = [], "", 0
    for char in path:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if depth < 0 or depth > 1:
            raise ValueError("Ruta de resultado no válida.")
        if char == "." and depth == 0:
            segments.append(current)
            current = ""
        else:
            current += char
    segments.append(current)
    if (
        depth
        or len(segments) > 16
        or any(not (part == "*" or part.isdecimal() or _TOKEN.fullmatch(part)) for part in segments)
    ):
        raise ValueError("Usa una ruta como status.remaining_mb o items[id=42].status.")
    return segments


def normalize_output(output: dict[str, str]) -> dict[str, JsonValue]:
    normalized: dict[str, JsonValue] = {}
    for key, value in output.items():
        try:
            normalized[key] = json.loads(value)
        except (ValueError, RecursionError):
            normalized[key] = value
    return normalized


def _equal(left: JsonValue, right: JsonValue) -> bool:
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _select(values: list[JsonValue], selector: str) -> list[JsonValue]:
    selected: list[JsonValue] = []
    for value in values:
        if selector == "*":
            if isinstance(value, list):
                selected.extend(value)
            elif isinstance(value, dict):
                selected.extend(value.values())
        elif selector.isdecimal():
            if isinstance(value, list) and int(selector) < len(value):
                selected.append(value[int(selector)])
        elif "=" in selector:
            key, expected = selector.split("=", 1)
            try:
                expected_value: JsonValue = json.loads(expected)
            except ValueError:
                expected_value = expected
            if isinstance(value, list):
                selected.extend(
                    item
                    for item in value
                    if isinstance(item, dict) and key in item and _equal(item[key], expected_value)
                )
        elif isinstance(value, dict) and selector in value:
            selected.append(value[selector])
    return selected


def selected_values(output: dict[str, JsonValue], path: str) -> list[JsonValue]:
    values: list[JsonValue] = [output]
    for segment in path_segments(path):
        match = _TOKEN.fullmatch(segment)
        if match:
            values = _select(values, match.group(1))
            if match.group(2) is not None:
                values = _select(values, match.group(2))
        else:
            values = _select(values, segment)
    return values


def _compare(value: JsonValue, condition: ResultCondition) -> bool:
    expected, operator = condition.value, condition.operator
    if operator == "equals":
        return _equal(value, expected)
    if operator == "not_equals":
        return not _equal(value, expected)
    if operator == "contains":
        if isinstance(value, str) and isinstance(expected, str):
            return expected in value
        if isinstance(value, list):
            return any(_equal(item, expected) for item in value)
    if operator == "is_empty":
        return isinstance(value, (list, dict, str)) and len(value) == 0
    if operator in {"gt", "gte", "lt", "lte"}:
        if (
            isinstance(value, bool)
            or isinstance(expected, bool)
            or not isinstance(value, (int, float))
            or not isinstance(expected, (int, float))
        ):
            return False
        if (isinstance(value, float) and not math.isfinite(value)) or (
            isinstance(expected, float) and not math.isfinite(expected)
        ):
            return False
        return {
            "gt": value > expected,
            "gte": value >= expected,
            "lt": value < expected,
            "lte": value <= expected,
        }[operator]
    return False


def validate_condition(condition: ResultCondition) -> None:
    path_segments(condition.path)
    if condition.operator in {"gt", "gte", "lt", "lte"} and (
        isinstance(condition.value, bool) or not isinstance(condition.value, (int, float))
    ):
        raise ValueError("La comparación numérica requiere un número.")


def evaluate_condition(
    output: dict[str, JsonValue],
    condition: ResultCondition,
    previous_hash: str | None = None,
) -> ConditionResult:
    validate_condition(condition)
    values = selected_values(output, condition.path)
    encoded = json.dumps(values, sort_keys=True, ensure_ascii=False)
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    if condition.operator == "changed":
        matched = previous_hash is not None and fingerprint != previous_hash
    elif condition.operator == "exists":
        matched = bool(values)
    elif condition.operator == "not_exists":
        matched = not values
    else:
        matched = any(_compare(value, condition) for value in values)
    return ConditionResult(matched, values, fingerprint, encoded[:1000])
