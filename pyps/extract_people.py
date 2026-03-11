#!/usr/bin/env python3
"""從 signup.json 取出每位參加者的姓名、身分證字號、出生年月日。"""

import argparse
import csv
import io
import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Extract name/idno/birthday from signup.json")
    parser.add_argument(
        "--signup",
        type=Path,
        default=root / "data" / "signup.json",
        help="Path to signup.json",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output CSV file (default: print to stdout)",
    )
    args = parser.parse_args()

    raw = args.signup.read_text(encoding="utf-8").strip()
    signups = json.loads(raw) if raw else []

    fields = ["姓名", "身分證字號", "出生年月日"]
    rows = []
    for record in signups:
        for person in record.get("people", []):
            rows.append([
                person.get("name", ""),
                person.get("idno", ""),
                person.get("birthday", ""),
            ])

    if args.output:
        with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(fields)
            writer.writerows(rows)
        print(f"已輸出 {len(rows)} 筆資料到 {args.output}")
    else:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(fields)
        writer.writerows(rows)
        print(buf.getvalue(), end="")


if __name__ == "__main__":
    main()
