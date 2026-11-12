"""Shared CSV formatting utilities with spreadsheet formula-injection protection."""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe_cell(value: Any) -> Any:
    """Escape leading formula characters on text cells while keeping numbers intact."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if text and text[0] in _FORMULA_PREFIXES:
        return "'" + text
    return text


def rows_to_csv_string(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    """Serialize headers and rows into a formula-safe CSV string."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([csv_safe_cell(h) for h in headers])
    for row in rows:
        writer.writerow([csv_safe_cell(cell) for cell in row])
    return buffer.getvalue()

