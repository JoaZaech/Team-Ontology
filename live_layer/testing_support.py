"""Helpers that let tests address checks by name instead of list position.

Check order and count both change as the rule catalogue grows. Assertions that
index into ``result["checks"]`` break for reasons unrelated to what they meant
to pin, so tests look checks up by name through these helpers instead.
"""

from __future__ import annotations

from typing import Any, Mapping


def check_named(result: Mapping[str, Any], name: str) -> dict[str, Any]:
    for check in result["checks"]:
        if check["name"] == name:
            return check
    available = sorted(check["name"] for check in result["checks"])
    raise AssertionError(f"no check named {name!r}; available checks: {available}")


def outcomes_by_name(result: Mapping[str, Any]) -> dict[str, str]:
    return {check["name"]: check["outcome"] for check in result["checks"]}


def check_names(result: Mapping[str, Any]) -> set[str]:
    return {check["name"] for check in result["checks"]}
