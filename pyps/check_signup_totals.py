#!/usr/bin/env python3
"""Validate signup totals against computed prices.

Reads:
- pyps/data/signup.json
- pyps/ticket.conf.json

For each signup record, recomputes expected total from:
- ticket type prices in ticket.conf.json
- bus cost (if transport == "bus")
- bento costs from record quantities

Then compares expected total with record['total'] and prints a report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_BENTO_PRICE = {
    "chicken": 130,
    "pork": 120,
    "veg": 120,
    "rice": 100,
}


class DataError(Exception):
    """Raised when input data is invalid."""


def load_json(path: Path, *, allow_blank: bool = False) -> Any:
    if not path.exists():
        raise DataError(f"File not found: {path}")

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        if allow_blank:
            return []
        raise DataError(f"File is empty: {path}")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataError(f"JSON parse failed for {path}: {exc}") from exc


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def compute_total(record: dict[str, Any], ticket_conf: dict[str, Any]) -> int:
    tickets = ticket_conf.get("tickets", {})
    bus_conf = ticket_conf.get("bus", {})

    people = record.get("people") or []
    total = 0
    participant_count = 0

    for person in people:
        ticket_type = person.get("type")
        if ticket_type in tickets:
            total += as_int(tickets[ticket_type].get("price"), 0)
        participant_count += 1

    transport = str(record.get("transport") or "").strip().lower()
    if transport == "bus":
        bus_price = as_int(bus_conf.get("price"), 0)
        total += participant_count * bus_price

    bento = record.get("bento") or {}
    for kind, unit_price in DEFAULT_BENTO_PRICE.items():
        total += as_int(bento.get(kind), 0) * unit_price

    return total


def get_member_names(record: dict[str, Any]) -> list[str]:
    """Return cleaned member names from record.people."""
    people = record.get("people") or []
    names: list[str] = []

    for person in people:
        raw_name = person.get("name") if isinstance(person, dict) else None
        cleaned = str(raw_name or "").strip()
        names.append(cleaned if cleaned else "(no-name)")

    return names


def validate_records(
    signups: list[dict[str, Any]], ticket_conf: dict[str, Any]
) -> tuple[int, int, set[str]]:
    ok_count = 0
    mismatch_count = 0
    all_member_names: set[str] = set()

    for idx, record in enumerate(signups, start=1):
        expected = compute_total(record, ticket_conf)
        saved = as_int(record.get("total"), 0)

        name = (record.get("name") or "").strip() or "(no-name)"
        created_at = (record.get("createdAt") or "").strip() or "(no-createdAt)"
        member_names = get_member_names(record)

        for member_name in member_names:
            if member_name != "(no-name)":
                all_member_names.add(member_name)

        member_display = ", ".join(member_names) if member_names else "(none)"

        if expected == saved:
            ok_count += 1
            print(
                f"[OK] #{idx} {name} | saved={saved} expected={expected} | {created_at}"
            )
        else:
            mismatch_count += 1
            print(
                f"[MISMATCH] #{idx} {name} | saved={saved} expected={expected} "
                f"diff={saved - expected} | {created_at}"
            )

        print(f"  members: {member_display}")

    return ok_count, mismatch_count, all_member_names


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Check whether signup totals match computed totals."
    )
    parser.add_argument(
        "--signup",
        type=Path,
        default=root / "data" / "signup.json",
        help="Path to signup.json (default: pyps/data/signup.json)",
    )
    parser.add_argument(
        "--ticket-conf",
        type=Path,
        default=root / "ticket.conf.json",
        help="Path to ticket.conf.json (default: pyps/ticket.conf.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        signups = load_json(args.signup, allow_blank=True)
        ticket_conf = load_json(args.ticket_conf)
    except DataError as exc:
        print(f"ERROR: {exc}")
        return 2

    if not isinstance(signups, list):
        print("ERROR: signup data must be a JSON array")
        return 2

    if not isinstance(ticket_conf, dict):
        print("ERROR: ticket config must be a JSON object")
        return 2

    total_records = len(signups)
    print(f"Loaded {total_records} signup record(s).")

    if total_records == 0:
        print("No data to validate.")
        return 0

    ok_count, mismatch_count, all_member_names = validate_records(signups, ticket_conf)

    print("-" * 60)
    print(f"Summary: total={total_records}, ok={ok_count}, mismatch={mismatch_count}")
    if all_member_names:
        print("All members:")
        for idx, member_name in enumerate(sorted(all_member_names), start=1):
            print(f"  {idx}. {member_name}")
    else:
        print("All members: (none)")

    # Non-zero exit on mismatch to support CI checks.
    return 1 if mismatch_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
