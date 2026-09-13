#!/usr/bin/env python3
"""Structural validation of a SemScan JSON report.

This is the assertion engine behind ``scripts/kick_the_tires.sh``. It lives in a
separate file so the same checks can be reused when validating the reports
produced for the paper's experiments.

Usage:
    python scripts/check_report.py REPORT.json [--mode auto|offline|llm]

Exit status:
    0  every check passed
    1  at least one check failed
    2  the report could not be read or parsed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# The bundled example is CVE-2023-6730: an unsafe pickle deserialization in the
# RAG retriever of transformers 4.35.2. These are the two locations declared in
# rules/sources.jsonl and rules/sinks.jsonl.
RAG_FILE = "src/transformers/models/rag/retrieval_rag.py"
EXPECTED_SOURCE = {"line": 419, "symbol": "retriever_name_or_path", "needle": "from_pretrained"}
EXPECTED_SINK = {"line": 135, "symbol": "passages_file", "needle": "pickle.load"}

MIN_REPO_FILES = 100
EXPECTED_LOCAL_FINDINGS = 2

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


class Checker:
    """Collects pass/fail results and prints them as they are evaluated."""

    def __init__(self) -> None:
        self.failures: List[str] = []
        self.passed = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  {GREEN}PASS{RESET}  {name}")
        else:
            self.failures.append(name)
            suffix = f"  {DIM}({detail}){RESET}" if detail else ""
            print(f"  {RED}FAIL{RESET}  {name}{suffix}")
        return ok

    def summary(self) -> int:
        total = self.passed + len(self.failures)
        if self.failures:
            print(f"\n{RED}{len(self.failures)} of {total} checks failed{RESET}")
            for name in self.failures:
                print(f"  - {name}")
            return 1
        print(f"\n{GREEN}all {total} checks passed{RESET}")
        return 0


def repo_files(report: Dict[str, Any]) -> List[str]:
    """Extract the repository file list from the repo_map finding."""
    raw = (report.get("repo_map") or {}).get("raw") or {}
    pipeline = raw.get("raw_pipeline_results") or raw.get("pipe_results") or {}
    for value in pipeline.values():
        if isinstance(value, dict) and isinstance(value.get("files"), list):
            return value["files"]
    files = raw.get("files")
    return files if isinstance(files, list) else []


def _locations(report: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    inputs = report.get("inputs") or {}
    value = inputs.get(key)
    return value if isinstance(value, list) else []


def _all_excerpts(finding: Dict[str, Any]) -> str:
    evidence = finding.get("evidence") or []
    return "\n".join(str(e.get("excerpt") or "") for e in evidence if isinstance(e, dict))


def check_common(c: Checker, report: Dict[str, Any]) -> None:
    print("report structure")
    meta = report.get("meta") or {}
    c.check("meta present", bool(meta))
    c.check("meta.language == 'python'", meta.get("language") == "python",
            f"got {meta.get('language')!r}")
    repo_root = str(meta.get("repo_root") or "")
    c.check("meta.repo_root points at transformers-4.35.2",
            repo_root.replace("\\", "/").rstrip("/").endswith("CVE-2023-6730/transformers-4.35.2"),
            f"got {repo_root!r}")

    print("inputs")
    sources = _locations(report, "sources")
    sinks = _locations(report, "sinks")
    c.check("exactly 1 source location", len(sources) == 1, f"got {len(sources)}")
    c.check("exactly 1 sink location", len(sinks) == 1, f"got {len(sinks)}")
    if sources:
        s = sources[0]
        c.check("source path is the RAG retriever",
                str(s.get("path", "")).replace("\\", "/").endswith(RAG_FILE), f"got {s.get('path')!r}")
        c.check(f"source line == {EXPECTED_SOURCE['line']}", s.get("line") == EXPECTED_SOURCE["line"],
                f"got {s.get('line')!r}")
        c.check(f"source symbol == {EXPECTED_SOURCE['symbol']}",
                s.get("symbol") == EXPECTED_SOURCE["symbol"], f"got {s.get('symbol')!r}")
    if sinks:
        s = sinks[0]
        c.check("sink path is the RAG retriever",
                str(s.get("path", "")).replace("\\", "/").endswith(RAG_FILE), f"got {s.get('path')!r}")
        c.check(f"sink line == {EXPECTED_SINK['line']}", s.get("line") == EXPECTED_SINK["line"],
                f"got {s.get('line')!r}")
        c.check(f"sink symbol == {EXPECTED_SINK['symbol']}",
                s.get("symbol") == EXPECTED_SINK["symbol"], f"got {s.get('symbol')!r}")

    print("repository analysis")
    files = repo_files(report)
    c.check(f"repo_map discovered >= {MIN_REPO_FILES} files", len(files) >= MIN_REPO_FILES,
            f"got {len(files)}")
    c.check("repo_map.role == 'repo_map'", (report.get("repo_map") or {}).get("role") == "repo_map")

    findings = report.get("local_findings") or []
    c.check(f"{EXPECTED_LOCAL_FINDINGS} local findings", len(findings) == EXPECTED_LOCAL_FINDINGS,
            f"got {len(findings)}")
    c.check("every finding is role 'local_context'",
            all(f.get("role") == "local_context" for f in findings if isinstance(f, dict)))
    c.check("every finding carries evidence",
            all((f.get("evidence") or []) for f in findings if isinstance(f, dict)))

    # Reading the real source text is what distinguishes a working tool run from
    # an empty skeleton, so assert on the actual code lines.
    text = "\n".join(_all_excerpts(f) for f in findings if isinstance(f, dict))
    c.check(f"evidence contains the source line ({EXPECTED_SOURCE['needle']!r})",
            EXPECTED_SOURCE["needle"] in text)
    c.check(f"evidence contains the sink line ({EXPECTED_SINK['needle']!r})",
            EXPECTED_SINK["needle"] in text)


def check_offline(c: Checker, report: Dict[str, Any]) -> None:
    print("offline mode")
    meta = report.get("meta") or {}
    c.check("meta.no_llm is true", meta.get("no_llm") is True, f"got {meta.get('no_llm')!r}")
    synthesis = report.get("synthesis") or {}
    c.check("synthesis.reachable == 'unknown'", synthesis.get("reachable") == "unknown",
            f"got {synthesis.get('reachable')!r}")


def check_llm(c: Checker, report: Dict[str, Any]) -> None:
    print("LLM mode")
    meta = report.get("meta") or {}
    c.check("meta.no_llm is false", meta.get("no_llm") is False, f"got {meta.get('no_llm')!r}")

    usage = meta.get("token_usage") or {}
    for role in ("planner", "worker"):
        entry = usage.get(role)
        c.check(f"{role} made at least one request",
                isinstance(entry, dict) and int(entry.get("requests") or 0) >= 1,
                f"got {entry!r}")
        c.check(f"{role} reported token usage",
                isinstance(entry, dict) and int(entry.get("total_tokens") or 0) > 0,
                f"got {entry!r}")

    synthesis = report.get("synthesis") or {}
    c.check("synthesis.reachable is a verdict",
            synthesis.get("reachable") in {"yes", "no", "unknown"},
            f"got {synthesis.get('reachable')!r}")
    c.check("synthesis.summary is non-empty", bool(str(synthesis.get("summary") or "").strip()))
    c.check("synthesis lists paths or gaps",
            bool(synthesis.get("paths")) or bool(synthesis.get("gaps")))


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a SemScan JSON report.")
    parser.add_argument("report", help="path to the report.json produced by SemScan")
    parser.add_argument("--mode", choices=("auto", "offline", "llm"), default="auto",
                        help="which checks to run (default: auto, inferred from meta.no_llm)")
    args = parser.parse_args(argv)

    path = Path(args.report)
    if not path.is_file():
        print(f"{RED}report not found:{RESET} {path}", file=sys.stderr)
        return 2
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"{RED}report is not valid JSON:{RESET} {exc}", file=sys.stderr)
        return 2

    mode = args.mode
    if mode == "auto":
        mode = "offline" if (report.get("meta") or {}).get("no_llm") is True else "llm"

    print(f"checking {path} (mode={mode})\n")
    checker = Checker()
    check_common(checker, report)
    if mode == "offline":
        check_offline(checker, report)
    else:
        check_llm(checker, report)
    return checker.summary()


if __name__ == "__main__":
    raise SystemExit(main())
