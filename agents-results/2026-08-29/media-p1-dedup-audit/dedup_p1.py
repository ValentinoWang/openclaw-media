#!/usr/bin/env python3
"""Reproducible P1 inventory and conservative cross-domain de-duplication."""
from __future__ import annotations
import argparse, json, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AUDIT = ROOT / "docs/production-reconciliation/20260827/pipeline-full-audit.md"
FOLLOWUP = ROOT / "docs/production-reconciliation/20260828/audit-followup-review.md"
PROGRESS = ROOT / "agents-results/2026-08-29/media-p1-remaining-development-paths/implementation-progress.md"

# Only aliases with an explicit same-root statement or identical contract are folded.
# Similar wording without this evidence remains separate by design.
ALIAS_GROUPS = {
    "review_draft_attribution": ["CD-06", "BIZ-04"],
    "material_feedback_loop": ["CD-14", "BIZ-09"],
    "reference_shots_whitelist": ["CPC-11", "BIZ-11"],
    "xiaohongshu_carousel_contract": ["CPC-12", "CC-04"],
    "business_stale_month_and_price": ["CPO-K04", "CC-07", "BIZ-17", "CR-26"],
    "frontmatter_model_contract": ["LP-11", "LB-12"],
    "model_tier_split": ["LP-10", "LH-07"],
    "review_json_user_rendering": ["BIZ-03", "CD-09", "CR-07", "CPO-K15"],
}

# Current-main evidence explicitly recorded by the follow-up/progress ledger.
CLOSED = {
    "CR-01": "533fc35", "CR-12": "533fc35", "CR-20": "42250af",
    "CPC-01": "5213a9a", "CPC-02": "5213a9a", "CPC-03": "5213a9a", "CPC-04": "5213a9a",
    "CPC-16": "a9f0942", "BIZ-01": "72fa092", "BIZ-03": "7226e02",
    "BIZ-08": "1e145bd", "BIZ-10": "707fdb2", "CD-09": "7226e02",
    "CR-07": "7226e02", "CPO-K15": "7226e02", "CRF-04": "978c60a",
    "RT-01": "b80151d", "RT-02": "dc4a089", "RT-03": "d32afca",
    "RT-04": "d833d24", "RT-08": "086ab71", "RT-12": "086ab71",
    "RT-13": "8e5b436", "RT-14": "086ab71", "CPO-N21": "f7d4ec3",
    "CD-03": "e48fccf", "CD-04": "e48fccf", "CD-05": "e48fccf",
    "CD-06": "e48fccf", "CD-07": "e48fccf", "CD-08": "e48fccf",
    "CD-02": "cedd7e9", "CD-10": "a248d8b", "CD-11": "7fe94e4",
    "CD-14": "7fe94e4", "CD-16": "0d6e8b8",
}

# Source and focused-test evidence exists, but the acceptance layer still needs
# production/runtime proof. These remain open and must not count as closed.
PARTIAL = {
    "BIZ-05": "ec8c88c",
    "CD-13": "ec8c88c",
}

def parse_items(text: str):
    out = {}
    for block in re.split(r"(?=^#### )", text, flags=re.M):
        m = re.match(r"####\s+([^｜|\s]+)[｜|](.+)", block)
        s = re.search(r"严重度 / 状态\*\*：[^/]+/\s*(P\d)\s*/\s*(未修复|部分修复|已修复)", block)
        if m and s and s.group(1) == "P1":
            out[m.group(1)] = {"id": m.group(1), "title": m.group(2).strip(), "baseline": s.group(2)}
    return out

def git_sha():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    items = parse_items(AUDIT.read_text())
    groups = {k: list(v) for k, v in ALIAS_GROUPS.items()}
    covered = {x for xs in groups.values() for x in xs}
    for item in items:
        if item not in covered:
            groups[f"singleton:{item}"] = [item]
    # A closure override is accepted only when the referenced commit is present in main history.
    hist = subprocess.check_output(["git", "log", "--format=%H"], cwd=ROOT, text=True).splitlines()
    hist_short = {h[:7] for h in hist}
    for v in CLOSED.values():
        if v not in hist_short:
            raise SystemExit(f"evidence commit {v} is absent from current main")
    for v in PARTIAL.values():
        if v not in hist_short:
            raise SystemExit(f"partial evidence commit {v} is absent from current main")
    records = []
    for key, ids in groups.items():
        present = [items[i] for i in ids if i in items]
        if not present: continue
        statuses = ["已修复" if x["id"] in CLOSED else ("部分修复" if x["id"] in PARTIAL else x["baseline"]) for x in present]
        status = "已修复" if all(x == "已修复" for x in statuses) else ("部分修复" if any(x in {"已修复", "部分修复"} for x in statuses) else "未修复")
        evidence = sorted({(CLOSED | PARTIAL)[x["id"]] for x in present if x["id"] in (CLOSED | PARTIAL)})
        records.append({"key": key, "ids": ids, "status": status, "evidence": evidence})
    result = {"source": str(AUDIT), "followup": str(FOLLOWUP), "progress": str(PROGRESS), "main": git_sha(), "raw_p1": len(items), "unique_dedup_p1": len(records), "groups": records}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2)); return
    print(f"raw_p1={len(items)} unique_dedup_p1={len(records)} main={git_sha()}")
    for r in records: print(f"{r['key']}\t{','.join(r['ids'])}\t{r['status']}\t{','.join(r['evidence'])}")

if __name__ == "__main__": main()
