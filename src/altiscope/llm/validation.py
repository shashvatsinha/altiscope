"""Bounded schema diagnostics without response values or exception prose."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

MAX_DIAGNOSTIC_CHARS = 512
MAX_DIAGNOSTIC_ERRORS = 8
_FALLBACK = "output: schema_validation_failed"
_CODES = frozenset(
    {
        "missing",
        "extra_forbidden",
        "string_type",
        "string_too_short",
        "string_too_long",
        "list_type",
        "too_short",
        "too_long",
        "int_type",
        "int_parsing",
        "float_type",
        "float_parsing",
        "bool_type",
        "bool_parsing",
        "dict_type",
        "model_type",
        "json_invalid",
        "json_type",
        "literal_error",
        "enum",
        "value_error",
        "schema_validation_failed",
    }
)


def _fields(output_type: type[BaseModel]) -> set[str]:
    names = {"output", "extra"}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(output_type.model_json_schema())
    return names


def sanitize_diagnostic(value: str | None, output_type: type[BaseModel]) -> str:
    """Accept only schema field/code pairs; reject arbitrary adapter error text.

    Keep at most eight entries and 512 characters, marking omitted entries with ... .
    Locations are field names only: no response keys, indices, values, context, URLs,
    custom validator messages, or SDK exception details can enter this channel.
    """
    if not value:
        return _FALLBACK
    fields = _fields(output_type)
    entries: list[str] = []
    truncated = len(value) > MAX_DIAGNOSTIC_CHARS
    for entry in value[:MAX_DIAGNOSTIC_CHARS].split("; "):
        if entry == "...":
            truncated = True
            break
        field, separator, code = entry.partition(": ")
        if not separator or field not in fields or code not in _CODES:
            return _FALLBACK
        if len(entries) == MAX_DIAGNOSTIC_ERRORS or len(
            "; ".join([*entries, entry])
        ) > MAX_DIAGNOSTIC_CHARS - len("; ..."):
            truncated = True
            break
        entries.append(entry)
    return "; ".join(entries) + ("; ..." if truncated else "") if entries else _FALLBACK


def validation_diagnostic(exc: ValidationError, output_type: type[BaseModel]) -> str:
    fields = _fields(output_type)
    entries: list[str] = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False)[
        :MAX_DIAGNOSTIC_ERRORS
    ]:
        code = error["type"] if error["type"] in _CODES else "schema_validation_failed"
        field = (
            "extra"
            if code == "extra_forbidden"
            else next(
                (
                    part
                    for part in reversed(error["loc"])
                    if isinstance(part, str) and part in fields
                ),
                "output",
            )
        )
        entries.append(f"{field}: {code}")
    if exc.error_count() > MAX_DIAGNOSTIC_ERRORS:
        entries.append("...")
    return sanitize_diagnostic("; ".join(entries), output_type)
