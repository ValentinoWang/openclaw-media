#!/usr/bin/env python3
"""Reject a Router pytest report that contains skipped test cases."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _declared_count(element: ET.Element, name: str) -> int | None:
    raw_value = element.attrib.get(name)
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"invalid {name} count: {raw_value}") from exc
    if value < 0:
        raise ValueError(f"invalid {name} count: {raw_value}")
    return value


def skipped_test_ids(report_path: Path) -> list[str]:
    root = ET.parse(report_path).getroot()
    if _local_name(root.tag) not in {"testsuite", "testsuites"}:
        raise ValueError(f"unexpected JUnit root: {_local_name(root.tag)}")
    testcases = [element for element in root.iter() if _local_name(element.tag) == "testcase"]
    if not testcases:
        raise ValueError("JUnit report contains no test cases")

    skipped: list[str] = []
    for testcase in testcases:
        if not any(_local_name(child.tag) == "skipped" for child in testcase):
            continue
        name = testcase.attrib.get("name", "<unknown>")
        class_name = testcase.attrib.get("classname", "")
        skipped.append(f"{class_name}::{name}" if class_name else name)

    for suite in (element for element in root.iter() if _local_name(element.tag) == "testsuite"):
        suite_cases = [element for element in suite.iter() if _local_name(element.tag) == "testcase"]
        declared_tests = _declared_count(suite, "tests")
        declared_skipped = _declared_count(suite, "skipped")
        actual_skipped = sum(
            any(_local_name(child.tag) == "skipped" for child in testcase)
            for testcase in suite_cases
        )
        if declared_tests is not None and declared_tests != len(suite_cases):
            raise ValueError(
                f"JUnit suite test count mismatch: declared {declared_tests}, found {len(suite_cases)}"
            )
        if declared_skipped is not None and declared_skipped != actual_skipped:
            raise ValueError(
                f"JUnit suite skip count mismatch: declared {declared_skipped}, found {actual_skipped}"
            )
    return skipped


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("Usage: check_pytest_junit.py PYTEST_JUNIT_XML", file=sys.stderr)
        return 2
    report_path = Path(arguments[0])
    try:
        skipped = skipped_test_ids(report_path)
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f"Unable to verify Router pytest skips: {report_path}: {exc}", file=sys.stderr)
        return 2
    if skipped:
        print(
            "Router pytest gate requires zero skipped tests. Repair the fixture or test environment:",
            file=sys.stderr,
        )
        for test_id in skipped:
            print(f"- {test_id}", file=sys.stderr)
        return 3
    print("Router pytest skip gate: 0 skipped tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
