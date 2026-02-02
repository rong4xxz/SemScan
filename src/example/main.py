"""
CLI entry: only parse arguments, call orchestration, print exit code/exception.
Do not load config, skills, or assemble report here.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

from example.orchestrator import run_analysis


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="example",
        description="New architecture skeleton: multi-Agent code data flow analysis",
    )
    p.add_argument("--repo-root", required=True, help="repository root path to be analyzed")
    p.add_argument("--language", required=True, help="programming language, e.g. python/javascript")
    p.add_argument("--source-file", required=True, help="source file path")
    p.add_argument("--sink-file", required=True, help="sink file path")
    p.add_argument("--out", default="report.json", help="output report path")
    p.add_argument("--no-llm", action="store_true", help="offline mode: do not call LLM")
    p.add_argument("--dotenv", default=".env", help=".env file name")
    p.add_argument("--max-rounds", type=int, default=5, help="main Agent comprehensive rounds (default 5)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_path = Path(args.out).resolve()

    try:
        asyncio.run(
            run_analysis(
                repo_root=args.repo_root,
                language=args.language,
                source_file=args.source_file,
                sink_file=args.sink_file,
                out_file=str(out_path),
                no_llm=args.no_llm,
                dotenv=args.dotenv,
                max_rounds=args.max_rounds,
            )
        )
    except Exception as e:
        print("[example] failed to run", file=sys.stderr)
        print(f"[example]   {type(e).__name__}: {e!r}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 2

    print(f"[example] done. report => {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
