#!/usr/bin/env python3
"""Fail when a remote branch carries changes not represented by canonical main.

This is a source-control gate only. It never updates or deletes refs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BranchResult:
    branch: str
    sha: str
    disposition: str
    unique_patch_count: int


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _sha(ref: str) -> str:
    return _git("rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()


def _is_ancestor(ref: str, main_ref: str) -> bool:
    return _git("merge-base", "--is-ancestor", ref, main_ref, check=False).returncode == 0


def _unique_patch_count(main_ref: str, ref: str) -> int:
    output = _git("cherry", main_ref, ref).stdout.splitlines()
    return sum(1 for line in output if line.startswith("+"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--allow-branch", action="append", default=[])
    args = parser.parse_args()

    main_sha = _sha(args.main_ref)
    allowed = {item.strip() for item in args.allow_branch if item.strip()}
    refs = [
        line.strip()
        for line in _git(
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/remotes/origin",
        ).stdout.splitlines()
        if line.strip() and line.strip() not in {"origin/HEAD", args.main_ref}
    ]

    results: list[BranchResult] = []
    failures: list[str] = []
    for ref in sorted(refs):
        short = ref.removeprefix("origin/")
        sha = _sha(ref)
        if short in allowed:
            disposition = "allowed_current_work"
            unique = _unique_patch_count(args.main_ref, ref)
        elif _is_ancestor(ref, args.main_ref):
            disposition = "merged_into_main"
            unique = 0
        else:
            unique = _unique_patch_count(args.main_ref, ref)
            disposition = "patch_equivalent" if unique == 0 else "unmerged_unique_changes"
            if unique:
                failures.append(short)
        results.append(BranchResult(short, sha, disposition, unique))

    print(
        json.dumps(
            {
                "schemaVersion": "openclaw.remote-branch-gate.v1",
                "mainRef": args.main_ref,
                "mainSha": main_sha,
                "allowedBranches": sorted(allowed),
                "branches": [asdict(item) for item in results],
                "ok": not failures,
                "failures": failures,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
