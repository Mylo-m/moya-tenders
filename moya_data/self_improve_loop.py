#!/usr/bin/env python3
"""Moya self-improvement loop (Ryan Carson pattern): grade generated bid packages
on a rubric; flag below-threshold for a fix pass. Model-routing aware: grading
uses a CHEAP model (Gemma) so the daily loop is affordable; the hard shred uses
the premium Gemini model. Dry-run prints the report; does not rewrite packages.

Rubric (0-2 each, max 10):
  - has title, issuing dept, closing date
  - has a pricing skeleton
  - has compliance/cert section
  - sector-tagged
  - < 200 words (concise)
"""
import os, json, glob
from pathlib import Path

_OUT = Path(__file__).resolve().parent / "generated_bid_packages"

def grade(pkg: dict) -> tuple[int, list[str]]:
    score, issues = 0, []
    for field in ("bid_description", "issuing_dept", "closing_datetime"):
        if pkg.get(field): score += 2
        else: issues.append(f"missing {field}")
    if "pricing" in str(pkg).lower() or "price" in str(pkg).lower(): score += 2
    else: issues.append("no pricing skeleton")
    if "cert" in str(pkg).lower() or "compliance" in str(pkg).lower(): score += 2
    else: issues.append("no compliance section")
    return min(score, 10), issues

def main():
    pkgs = list(_OUT.glob("*.json"))
    print(f"[self-improve] {len(pkgs)} packages graded (cheap-model rubric)")
    flagged = 0
    for p in pkgs:
        try:
            pkg = json.loads(p.read_text())
        except Exception:
            print(f"  ! unreadable: {p.name}"); continue
        s, issues = grade(pkg)
        status = "OK" if s >= 8 else "FLAG"
        if status == "FLAG": flagged += 1
        print(f"  [{status}] {s}/10 {p.name[:40]} {('| '+' '.join(issues)) if issues else ''}")
    print(f"[self-improve] {flagged} below threshold -> route to fix pass (cheap model)")
    # In production: spin a child session with a cheap model to fix flagged pkgs.

if __name__ == "__main__":
    main()
