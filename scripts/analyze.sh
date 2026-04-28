#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <repo_root> <language> [source_file sink_file] [out_json] [--no-llm] [--dotenv FILE] [--max-rounds N]" >&2
  echo "  - Explicit rule files must both be .jsonl or both be .yaml" >&2
  echo "  - If rule files are omitted, defaults to ./rules/source.yaml + ./rules/sink.yaml" >&2
  echo "    or ./rules/sources.jsonl + ./rules/sinks.jsonl" >&2
  exit 2
fi

REPO_ROOT="$1"; shift
LANGUAGE="$1"; shift

MODE="default"
SOURCE_FILE=""
SINK_FILE=""

# Explicit source/sink files: accept both jsonl and yaml.
if [[ $# -ge 2 ]]; then
  case "${1:-}:${2:-}" in
    *.jsonl:*.jsonl|*.yaml:*.yaml)
      MODE="explicit"
      SOURCE_FILE="$1"; shift
      SINK_FILE="$1"; shift
      ;;
  esac
fi

# Optional args:
# - out_json (positional, optional)
# - --no-llm (flag, optional)
# - --dotenv FILE
# - --max-rounds N
OUT_FILE=""
NO_LLM="false"
DOTENV_FILE=""
MAX_ROUNDS=""
while [[ $# -gt 0 ]]; do
  arg="$1"
  if [[ "$arg" == "--no-llm" ]]; then
    NO_LLM="true"
    shift
  elif [[ "$arg" == "--dotenv" ]]; then
    if [[ $# -lt 2 ]]; then
      echo "Missing value for --dotenv" >&2
      exit 2
    fi
    DOTENV_FILE="$2"
    shift 2
  elif [[ "$arg" == "--max-rounds" ]]; then
    if [[ $# -lt 2 ]]; then
      echo "Missing value for --max-rounds" >&2
      exit 2
    fi
    MAX_ROUNDS="$2"
    shift 2
  elif [[ -z "$OUT_FILE" ]]; then
    OUT_FILE="$arg"
    shift
  else
    echo "Unknown extra arg: $arg" >&2
    echo "Usage: $0 <repo_root> <language> [source_file sink_file] [out_json] [--no-llm] [--dotenv FILE] [--max-rounds N]" >&2
    exit 2
  fi
done
OUT_FILE="${OUT_FILE:-report.json}"

EXTRA_ARGS=()
if [[ "$NO_LLM" == "true" ]]; then
  EXTRA_ARGS+=("--no-llm")
fi
if [[ -n "$DOTENV_FILE" ]]; then
  EXTRA_ARGS+=("--dotenv" "$DOTENV_FILE")
fi
if [[ -n "$MAX_ROUNDS" ]]; then
  EXTRA_ARGS+=("--max-rounds" "$MAX_ROUNDS")
fi

if [[ "$MODE" == "default" ]]; then
  if [[ -f "./rules/source.yaml" && -f "./rules/sink.yaml" ]]; then
    SOURCE_FILE="./rules/source.yaml"
    SINK_FILE="./rules/sink.yaml"
  elif [[ -f "./rules/sources.jsonl" && -f "./rules/sinks.jsonl" ]]; then
    SOURCE_FILE="./rules/sources.jsonl"
    SINK_FILE="./rules/sinks.jsonl"
  else
    echo "No default source/sink files found under ./rules" >&2
    echo "Expected either source.yaml + sink.yaml, or sources.jsonl + sinks.jsonl" >&2
    exit 2
  fi
fi

INPUT_ARGS=("--source-file" "$SOURCE_FILE" "--sink-file" "$SINK_FILE")

PYTHONPATH="${PYTHONPATH:-}"
if [[ -z "$PYTHONPATH" ]]; then
  export PYTHONPATH="$(pwd)/src"
else
  export PYTHONPATH="$(pwd)/src:$PYTHONPATH"
fi

PYTHON_BIN="python"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

"$PYTHON_BIN" -m semscan.main \
  --repo-root "$REPO_ROOT" \
  --language "$LANGUAGE" \
  "${INPUT_ARGS[@]}" \
  --out "$OUT_FILE" \
  "${EXTRA_ARGS[@]}"
