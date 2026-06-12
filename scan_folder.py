#!/usr/bin/env python3
"""Run Revelio across a folder of PDFs and rank what it finds.

This is the "go hunting" tool: point it at a directory of public documents and
it scans every PDF, then prints a summary sorted with the most serious findings
first. Optionally writes a Markdown report you can build a write-up from.

    python scan_folder.py ./documents
    python scan_folder.py ./documents --recursive --report FINDINGS.md
    python scan_folder.py ./documents --notable-only
    python scan_folder.py ./documents --json results.json

A note on handling results: recovered text can be genuinely sensitive (that's the
point). If you publish anything, report *that* a document leaked, not the leaked
content itself, and consider responsible disclosure to the document's owner.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from dataclasses import asdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import revelio  # noqa: E402

SEV_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
# the findings that are actually newsworthy: real leaks and tampering
NOTABLE = {"covered", "ocr-covered", "rev-added", "rev-removed", "c2pa-invalid"}


def _pdfs(folder: str, recursive: bool) -> list[str]:
    out = []
    if recursive:
        for root, _, files in os.walk(folder):
            out += [os.path.join(root, f) for f in files if f.lower().endswith(".pdf")]
    else:
        out += [os.path.join(folder, f) for f in os.listdir(folder)
                if f.lower().endswith(".pdf")]
    return sorted(out)


def _headline(findings: list) -> str:
    if not findings:
        return ""
    ranked = sorted(findings, key=lambda f: (SEV_RANK.get(f.severity, 9),
                                             f.kind not in NOTABLE))
    f = ranked[0]
    loc = f"p{f.page}" if f.page > 0 else (f.text[:24] if f.text else "doc")
    snippet = ""
    if f.kind in ("covered", "ocr-covered", "invisible", "microfont") and f.text:
        snippet = repr(f.text[:48])
    elif f.kind in ("rev-added", "rev-removed") and ": " in f.detail:
        snippet = f.detail.split(": ", 1)[-1][:48]  # the changed text lives in the detail
    return f"{f.kind} {loc}" + (f": {snippet}" if snippet else "")


def scan_one(path: str) -> dict:
    try:
        findings = revelio.scan(path)
    except Exception as e:  # noqa: BLE001 — one bad file shouldn't stop the batch
        return {"path": path, "error": str(e)}
    worst = min((SEV_RANK.get(f.severity, 9) for f in findings), default=9)
    return {
        "path": path,
        "findings": findings,
        "count": len(findings),
        "worst": worst,
        "notable": sum(1 for f in findings if f.kind in NOTABLE),
        "headline": _headline(findings),
    }


def _worst_label(worst: int) -> str:
    return {0: "HIGH", 1: "MED", 2: "LOW", 3: "INFO"}.get(worst, "ok")


def run(folder: str, recursive: bool) -> list[dict]:
    files = _pdfs(folder, recursive)
    results = []
    for i, p in enumerate(files, 1):
        print(f"\r  scanning {i}/{len(files)}…", end="", file=sys.stderr, flush=True)
        results.append(scan_one(p))
    print("\r" + " " * 40 + "\r", end="", file=sys.stderr)
    # errors last; otherwise worst severity, then most findings, then name
    results.sort(key=lambda r: (("error" in r), r.get("worst", 9),
                                -r.get("count", 0), r["path"].lower()))
    return files, results


def print_summary(results: list[dict], notable_only: bool) -> None:
    rows = [r for r in results if not notable_only or r.get("notable")]
    if not rows:
        print("No notable findings." if notable_only else "No PDFs scanned.")
        return
    print(f"{'WORST':<6} {'N':>3} {'!':>3}  {'FILE':<34} HEADLINE")
    print("-" * 96)
    for r in rows:
        name = os.path.basename(r["path"])[:34]
        if "error" in r:
            print(f"{'ERR':<6} {'-':>3} {'-':>3}  {name:<34} could not read: {r['error'][:30]}")
            continue
        print(f"{_worst_label(r['worst']):<6} {r['count']:>3} {r['notable']:>3}  "
              f"{name:<34} {r['headline']}")


def write_report(path: str, folder: str, results: list[dict]) -> None:
    scanned = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]
    with_find = [r for r in scanned if r["count"]]
    notable = [r for r in scanned if r["notable"]]
    lines = [
        "# Revelio batch findings", "",
        f"- Scanned: **{len(scanned)}** PDFs in `{folder}`"
        + (f" (+{len(errors)} unreadable)" if errors else ""),
        f"- With any finding: **{len(with_find)}**",
        f"- With a notable finding (leak / tamper): **{len(notable)}**",
        f"- Generated: {_dt.date.today().isoformat()}", "",
        "> Recovered text can be sensitive. Report *that* a document leaked, not the "
        "content; consider responsible disclosure to the owner.", "",
        "## Notable", "",
    ]
    if notable:
        lines += ["| File | Worst | Notable | Headline |", "|---|---|---|---|"]
        for r in sorted(notable, key=lambda r: (r["worst"], -r["count"])):
            lines.append(f"| {os.path.basename(r['path'])} | {_worst_label(r['worst'])} "
                         f"| {r['notable']} | {r['headline'].replace('|', '/')} |")
    else:
        lines.append("_No leaks or tampering surfaced in this batch._")
    lines += ["", "## All files with findings", "",
              "| File | Findings | Worst |", "|---|---|---|"]
    for r in sorted(with_find, key=lambda r: (r["worst"], -r["count"])):
        lines.append(f"| {os.path.basename(r['path'])} | {r['count']} | {_worst_label(r['worst'])} |")
    if errors:
        lines += ["", "## Unreadable", ""]
        lines += [f"- {os.path.basename(r['path'])}: {r['error']}" for r in errors]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nreport written to {path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run Revelio across a folder of PDFs.")
    ap.add_argument("folder", help="directory of PDFs to scan")
    ap.add_argument("--recursive", action="store_true", help="descend into subfolders")
    ap.add_argument("--notable-only", action="store_true",
                    help="summary shows only files with leaks/tampering")
    ap.add_argument("--report", metavar="FILE.md", help="write a Markdown report")
    ap.add_argument("--json", metavar="FILE.json", help="write full results as JSON")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.folder):
        print(f"not a folder: {args.folder}", file=sys.stderr)
        return 2

    files, results = run(args.folder, args.recursive)
    if not files:
        print("no PDFs found.")
        return 0

    print_summary(results, args.notable_only)
    if args.json:
        serial = [{**{k: v for k, v in r.items() if k != "findings"},
                   "findings": [asdict(f) for f in r.get("findings", [])]} for r in results]
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(serial, fh, indent=2)
        print(f"\njson written to {args.json}")
    if args.report:
        write_report(args.report, args.folder, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
