"""
CLI entrypoint: only parses arguments, invokes orchestration, and prints exit codes/errors.
It does not load config, skills, or assemble reports here.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

from semscan.orchestrator import ConfigurationError, run_analysis


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="semscan",
        description="New architecture skeleton: multi-agent code data-flow analysis (aligned with semscan behavior)",
    )
    p.add_argument("--repo-root", required=True, help="Repository root path to analyze")
    p.add_argument("--language", required=True, help="Programming language, e.g. python/javascript")
    p.add_argument("--source-file", required=True, help="Path to the source file list")
    p.add_argument("--sink-file", required=True, help="Path to the sink file list")
    p.add_argument("--out", default="report.json", help="Output report path")
    p.add_argument("--no-llm", action="store_true", help="Offline mode: do not call the LLM")
    p.add_argument("--dotenv", default=".env", help="Name of the .env file")
    p.add_argument("--max-rounds", type=int, default=5, help="Maximum synthesis rounds for the main agent (default: 5)")
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
    except ConfigurationError as e:
        # Configuration problems are user errors, so report them without a traceback.
        print("[semscan] configuration error", file=sys.stderr)
        print(f"[semscan]   {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print("[semscan] run failed", file=sys.stderr)
        print(f"[semscan]   {type(e).__name__}: {e!r}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 2

    print(f"[semscan] done. report => {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
