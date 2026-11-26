"""Pure helpers to diff two shadow ``reported`` snapshots (no Home Assistant import).

Used by the coordinator to log every D-code change at debug level. This makes
reverse-engineering a new model a matter of: enable debug logging, step through
every function in the Philips app once, download the log.
"""
from __future__ import annotations

from typing import Any

# Keys that change constantly and carry no user-facing meaning. Logging them
# would drown the interesting lines during a function sweep.
NOISY_KEYS = frozenset({
    "Runtime",       # uptime counter
    "rssi",          # WiFi signal
    "free_memory",   # heap
    # D03105 is deliberately NOT ignored: on the CX3550 it looked like an ack
    # flag, but on other models (CX7550) it is a real setting (display
    # brightness), so it must stay visible in a sweep log.
})


# Identifying keys: their values are masked in log output so a debug log can be
# shared in an issue without leaking device ids, serial or the user's device name.
LOG_REDACT_KEYS = frozenset({"DeviceId", "ProductId", "D01S0D", "D01S03", "registration_id"})


def diff_reported(
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
    ignore: frozenset[str] = NOISY_KEYS,
) -> list[tuple[str, Any, Any]]:
    """Return ``[(key, old_value, new_value), ...]`` for keys whose value changed.

    Keys only present on one side are reported with ``None`` on the other side.
    Keys in ``ignore`` are skipped. Result is sorted by key for stable logs.
    """
    old = old or {}
    new = new or {}
    changes: list[tuple[str, Any, Any]] = []
    for key in sorted(set(old) | set(new)):
        if key in ignore:
            continue
        before, after = old.get(key), new.get(key)
        if before != after:
            changes.append((key, before, after))
    return changes


def format_changes(
    changes: list[tuple[str, Any, Any]],
    redact: frozenset[str] = LOG_REDACT_KEYS,
) -> str:
    """Render changes as ``D0310D: 6 -> 7, D0320F: 0 -> 23040``.

    Values of keys in ``redact`` are replaced by ``***``.
    """
    parts = []
    for key, before, after in changes:
        if key in redact:
            parts.append(f"{key}: ***")
        else:
            parts.append(f"{key}: {before!r} -> {after!r}")
    return ", ".join(parts)
