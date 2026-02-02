#!/usr/bin/env bash
# Usage: ./scripts/analyze.sh /path/to/repo -l python -source source.jsonl -sink sink.jsonl
# If omnivul is installed (pip install -e .), the script will call it; otherwise runs via python -m example.main.

set -e

usage() {
    echo "Usage: $0 <repo_path> -l <language> -source <source.jsonl> -sink <sink.jsonl> [-o report.json]"
    echo "  repo_path    repository root path to analyze"
    echo "  -l           language, e.g. python"
    echo "  -source      source definition file (JSONL)"
    echo "  -sink        sink definition file (JSONL)"
    echo "  -o           optional, output report path (default: report.json)"
    exit 1
}

REPO_ROOT=""
LANG=""
SOURCE_FILE=""
SINK_FILE=""
OUT_FILE="report.json"

if [[ $# -lt 7 ]]; then
    usage
fi

REPO_ROOT="$1"
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        -l)
            LANG="$2"
            shift 2
            ;;
        -source)
            SOURCE_FILE="$2"
            shift 2
            ;;
        -sink)
            SINK_FILE="$2"
            shift 2
            ;;
        -o)
            OUT_FILE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            ;;
    esac
done

if [[ -z "$REPO_ROOT" || -z "$LANG" || -z "$SOURCE_FILE" || -z "$SINK_FILE" ]]; then
    echo "Missing required argument." >&2
    usage
fi

if [[ ! -d "$REPO_ROOT" ]]; then
    echo "Repo path is not a directory: $REPO_ROOT" >&2
    exit 2
fi

if [[ ! -f "$SOURCE_FILE" ]]; then
    echo "Source file not found: $SOURCE_FILE" >&2
    exit 2
fi

if [[ ! -f "$SINK_FILE" ]]; then
    echo "Sink file not found: $SINK_FILE" >&2
    exit 2
fi

# Project root: parent of the directory containing this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

run_omnivul() {
    if command -v omnivul &>/dev/null; then
        omnivul --repo-root "$REPO_ROOT" --language "$LANG" --source-file "$SOURCE_FILE" --sink-file "$SINK_FILE" --out "$OUT_FILE"
    else
        (cd "$PROJECT_ROOT" && PYTHONPATH=src python -m example.main \
            --repo-root "$REPO_ROOT" \
            --language "$LANG" \
            --source-file "$SOURCE_FILE" \
            --sink-file "$SINK_FILE" \
            --out "$OUT_FILE")
    fi
}

run_omnivul
