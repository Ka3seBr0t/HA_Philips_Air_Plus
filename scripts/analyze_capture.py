#!/usr/bin/env python3
"""
analyze_capture.py — Turn a raw_shadow.jsonl capture into a property-change report.

Reads the append-only capture written by shadow_dump.py and, per channel
(namespace = "shadow" or "ncp:<Port>"), builds a timeline for every property
key: when it first appeared and every time its value changed. Keys that never
changed are listed separately (identity / idle sensors); keys that DID change
during the sweep are the actionable ones that map to fan functions.

This is the Phase 2 diff step: correlate the printed change timestamps with the
wall-clock notes from the function sweep to read off
    property -> action -> value-encoding.

Usage:
  python analyze_capture.py                         # reads ../captures/raw_shadow.jsonl
  python analyze_capture.py --in path/to.jsonl
  python analyze_capture.py --changed-only          # hide constant keys
  python analyze_capture.py --since 2026-06-25T19:40:00Z   # ignore earlier lines
"""
from __future__ import annotations

import argparse
import json
import os
from collections import OrderedDict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IN = os.path.join(os.path.dirname(SCRIPT_DIR), "captures", "raw_shadow.jsonl")


def flatten(obj, prefix: str = "") -> dict:
    """Flatten nested dicts to dotted keys; leave scalars/lists as values."""
    out: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(flatten(v, key))
            else:
                out[key] = v
    return out


def reduce_record(topic: str, payload) -> tuple[str, dict] | None:
    """Map one captured message to (namespace, {property: value})."""
    if not isinstance(payload, dict):
        return None
    if topic.endswith("/from_ncp"):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("properties"), dict):
            return f"ncp:{data.get('portName', '?')}", flatten(data["properties"])
        return None
    if "/shadow/" in topic:
        state = payload.get("state", {})
        if isinstance(state, dict):
            reported = state.get("reported")
            if isinstance(reported, dict):
                return "shadow", flatten(reported)
    return None


def jval(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff a raw_shadow.jsonl capture into a change report.")
    ap.add_argument("--in", dest="infile", default=DEFAULT_IN, help="Capture file (JSON lines).")
    ap.add_argument("--changed-only", action="store_true", help="Show only keys that changed.")
    ap.add_argument("--since", default=None, help="Ignore records with ts < this ISO string.")
    args = ap.parse_args()

    if not os.path.isfile(args.infile):
        print(f"No capture file at {args.infile}. Run shadow_dump.py first.")
        return 1

    # namespace -> key -> list of (ts, value) recorded only when value changes
    timelines: "OrderedDict[str, OrderedDict[str, list]]" = OrderedDict()
    last: dict = {}
    n_records = 0

    with open(args.infile, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = rec.get("ts", "")
            if args.since and ts < args.since:
                continue
            reduced = reduce_record(rec.get("topic", ""), rec.get("payload"))
            if not reduced:
                continue
            n_records += 1
            ns, props = reduced
            ns_tl = timelines.setdefault(ns, OrderedDict())
            ns_last = last.setdefault(ns, {})
            for k, v in props.items():
                if k not in ns_last:
                    ns_tl.setdefault(k, []).append((ts, v))
                    ns_last[k] = v
                elif ns_last[k] != v:
                    ns_tl.setdefault(k, []).append((ts, v))
                    ns_last[k] = v

    if not timelines:
        print(f"Parsed {args.infile} but found no shadow/NCP property records.")
        return 1

    print(f"# Capture analysis - {args.infile}")
    print(f"# {n_records} property-bearing records across {len(timelines)} channel(s)\n")

    for ns, keys in timelines.items():
        changing = {k: tl for k, tl in keys.items() if len(tl) > 1}
        constant = {k: tl for k, tl in keys.items() if len(tl) == 1}

        print(f"== {ns} ==")
        print(f"   {len(changing)} changing key(s), {len(constant)} constant key(s)")

        if changing:
            print("   --- CHANGING (map these to functions) ---")
            for k, tl in sorted(changing.items(), key=lambda kv: -len(kv[1])):
                steps = "  ".join(f"{ts}={jval(v)}" for ts, v in tl)
                print(f"   {k:14} [{len(tl)-1} change(s)]  {steps}")

        if constant and not args.changed_only:
            print("   --- CONSTANT (identity / idle sensors) ---")
            for k, tl in constant.items():
                print(f"   {k:14} = {jval(tl[0][1])}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
