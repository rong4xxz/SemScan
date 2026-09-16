#!/usr/bin/env bash
#
# SemScan single-case runner.
#
# Usage:
#   ./scripts/analyze.sh <repo_root> [options]
#
# The analysis language is fixed to Python: SemScan's static tooling is built on
# Python's own `ast` module.
#
# Options:
#   --source FILE     source rule file (.jsonl or .yaml)
#   --sink FILE       sink rule file (.jsonl or .yaml)
#   --out FILE        output report path
#   --no-llm          offline mode; no API key required
#   --dotenv FILE     environment file (default: <root>/.env)
#   --max-rounds N    planner rounds (default: 5)
#   -h, --help        show this help
#
# Without --source/--sink the bundled example is used:
#   rules/bench/CVE-2023-6730/source.jsonl + sink.jsonl
#
# Default output: result/single/<timestamp>/report.json
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

die() { printf '\033[1;31m[analyze] ERROR:\033[0m %s\n' "$*" >&2; exit 2; }

usage() {
  cat <<'USAGE'
SemScan single-case runner.

Usage:
  ./scripts/analyze.sh <repo_root> [options]

Options:
  --source FILE     source rule file (.jsonl or .yaml)
  --sink FILE       sink rule file (.jsonl or .yaml)
  --out FILE        output report path
  --no-llm          offline mode; no API key required
  --dotenv FILE     environment file (default: <root>/.env)
  --max-rounds N    planner rounds (default: 5)
  -h, --help        show this help

The analysis language is fixed to Python.

Without --source/--sink the bundled example is used:
  rules/bench/CVE-2023-6730/source.jsonl + sink.jsonl

Default output: result/single/<timestamp>/report.json
USAGE
  exit 0
}

if [[ $# -ge 1 ]]; then
  if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage
  fi
fi
if [[ $# -lt 1 ]]; then
  usage
fi

TARGET_REPO="$1"; shift
# SemScan's static analysis is built on Python's own `ast` module, so the
# language is fixed rather than being a required argument.
LANGUAGE="python"

SOURCE_FILE=""
SINK_FILE=""
OUT_FILE=""
NO_LLM=0
MAX_ROUNDS=""
# SemScan resolves relative --dotenv paths against the current working
# directory, so pin it to the repository root to stay independent of where this
# script is invoked from.
DOTENV_FILE="${DOTENV_FILE:-${ROOT_DIR}/.env}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)     if [[ $# -lt 2 ]]; then die "--source requires a value"; fi;     SOURCE_FILE="$2"; shift 2 ;;
    --sink)       if [[ $# -lt 2 ]]; then die "--sink requires a value"; fi;       SINK_FILE="$2";   shift 2 ;;
    --out)        if [[ $# -lt 2 ]]; then die "--out requires a value"; fi;        OUT_FILE="$2";    shift 2 ;;
    --dotenv)     if [[ $# -lt 2 ]]; then die "--dotenv requires a value"; fi;     DOTENV_FILE="$2"; shift 2 ;;
    --max-rounds) if [[ $# -lt 2 ]]; then die "--max-rounds requires a value"; fi; MAX_ROUNDS="$2";  shift 2 ;;
    --no-llm)     NO_LLM=1; shift ;;
    -h|--help)    usage ;;
    *)            die "unknown argument: $1 (try --help)" ;;
  esac
done

if [[ ! -d "$TARGET_REPO" ]]; then
  die "repository not found: $TARGET_REPO"
fi
REPO_ABS="$(cd "$TARGET_REPO" && pwd)"

# Fall back to the bundled example.
if [[ -z "$SOURCE_FILE" ]]; then
  SOURCE_FILE="${ROOT_DIR}/rules/bench/CVE-2023-6730/source.jsonl"
fi
if [[ -z "$SINK_FILE" ]]; then
  SINK_FILE="${ROOT_DIR}/rules/bench/CVE-2023-6730/sink.jsonl"
fi
if [[ ! -f "$SOURCE_FILE" ]]; then die "source rule file not found: $SOURCE_FILE"; fi
if [[ ! -f "$SINK_FILE" ]]; then die "sink rule file not found:   $SINK_FILE"; fi

# Both rule files must use the same format.
SRC_EXT="${SOURCE_FILE##*.}"
SINK_EXT="${SINK_FILE##*.}"
if [[ "$SRC_EXT" != "$SINK_EXT" ]]; then
  die "source and sink must share one format (both .jsonl or both .yaml)"
fi
if [[ "$SRC_EXT" != "jsonl" && "$SRC_EXT" != "yaml" ]]; then
  die "rule files must be .jsonl or .yaml (got .$SRC_EXT)"
fi

# Default output: result/single/<timestamp>/report.json
if [[ -z "$OUT_FILE" ]]; then
  TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
  OUT_FILE="${ROOT_DIR}/result/single/${TIMESTAMP}/report.json"
fi
mkdir -p "$(dirname "$OUT_FILE")"
OUT_FILE="$(cd "$(dirname "$OUT_FILE")" && pwd)/$(basename "$OUT_FILE")"

PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  die "no Python interpreter found; run ./scripts/install.sh first"
fi

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

# Precheck: every rule path must exist under the repository root.
#
# Pointing --repo-root at a parent directory of the repository does not crash the
# run: the exit code stays 0, but the tools cannot open any file, so the report's
# "evidence" ends up being the pipeline error text instead of source code.
# Catch that here rather than producing a meaningless report.
if ! "${PYTHON_BIN}" - "${REPO_ABS}" "${SOURCE_FILE}" "${SINK_FILE}" <<'PRECHECK'
import sys
from pathlib import Path

from semscan.schemas import load_locations_jsonl, load_locations_yaml

repo = Path(sys.argv[1])
missing = []
total = 0
for rules_file in sys.argv[2:]:
    text = Path(rules_file).read_text(encoding="utf-8", errors="replace")
    if rules_file.endswith(".yaml"):
        locations = load_locations_yaml(text)
    else:
        locations = load_locations_jsonl(text)
    for loc in locations:
        total += 1
        if not (repo / loc.path).is_file():
            missing.append((Path(rules_file).name, loc.path))

if missing:
    print("Rule paths that do not exist under the repository root:", file=sys.stderr)
    for name, rel in missing:
        print(f"  {rel}  (declared in {name})", file=sys.stderr)
    print(f"\n  repository root: {repo}", file=sys.stderr)
    print("  hint: --repo-root must be the repository directory itself,", file=sys.stderr)
    print("        not a parent directory that contains it.", file=sys.stderr)
    sys.exit(1)

if total == 0:
    print("No source/sink locations were found in the rule files.", file=sys.stderr)
    sys.exit(1)
PRECHECK
then
  printf '\033[1;31m[analyze] ERROR:\033[0m rule precheck failed (see above)\n' >&2
  exit 2
fi

if [[ $NO_LLM -eq 1 ]]; then MODE="offline"; else MODE="LLM"; fi

printf '\n\033[1;36m==> SemScan single-case run\033[0m\n'
cat <<EOF
  repository   : ${REPO_ABS}
  language     : ${LANGUAGE}
  source rules : ${SOURCE_FILE}
  sink rules   : ${SINK_FILE}
  mode         : ${MODE}
  output       : ${OUT_FILE}
EOF
printf '\n'

ARGS=(
  -m semscan.main
  --repo-root "${REPO_ABS}"
  --language "${LANGUAGE}"
  --source-file "${SOURCE_FILE}"
  --sink-file "${SINK_FILE}"
  --dotenv "${DOTENV_FILE}"
  --out "${OUT_FILE}"
)
if [[ $NO_LLM -eq 1 ]]; then
  ARGS+=(--no-llm)
fi
if [[ -n "$MAX_ROUNDS" ]]; then
  ARGS+=(--max-rounds "${MAX_ROUNDS}")
fi

"${PYTHON_BIN}" "${ARGS[@]}"

printf '\n\033[1;36m==> Done\033[0m\n'
echo "  report: ${OUT_FILE}"
