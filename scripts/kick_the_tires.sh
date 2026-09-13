#!/usr/bin/env bash
#
# SemScan "kick the tires" smoke test.
#
# Purpose: show, in a few minutes, that the environment is installed correctly
# and that the analysis pipeline is wired up properly. The workload is
# deliberately minimal: one source, one sink, one bundled target repository
# (CVE-2023-6730, an unsafe pickle deserialization in the RAG retriever of
# transformers 4.35.2).
#
# Phase 1 is fully offline, deterministic and needs no API key.
# Phase 2 exercises the LLM planner and is skipped automatically when no API key
# is configured (SemScan exits with status 3 in that case).
#
# Usage:
#   ./scripts/kick_the_tires.sh [--skip-llm] [--max-rounds N] [--out-dir DIR]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET_REPO="${REPO_ROOT}/CVE-2023-6730/transformers-4.35.2"
SOURCE_RULES="${REPO_ROOT}/rules/sources.jsonl"
SINK_RULES="${REPO_ROOT}/rules/sinks.jsonl"
OUT_DIR="${REPO_ROOT}/kick_the_tires_out"
MAX_ROUNDS=1
SKIP_LLM=0
LLM_REPORT=""
# SemScan resolves relative --dotenv paths against the current working
# directory, so pin it to the repository root to stay independent of where this
# script is invoked from.
DOTENV_FILE="${DOTENV_FILE:-${REPO_ROOT}/.env}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  OK:\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  WARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\n\033[1;31mFAILED:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
SemScan kick-the-tires smoke test.

Usage:
  ./scripts/kick_the_tires.sh [options]

Options:
  --skip-llm          run only the offline phase
  --max-rounds N      planner rounds for the LLM phase (default: 1)
  --out-dir DIR       where reports and logs are written
                      (default: ./kick_the_tires_out)
  -h, --help          show this help
USAGE
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-llm)   SKIP_LLM=1; shift ;;
    --max-rounds) [[ $# -ge 2 ]] || die "--max-rounds requires a value"; MAX_ROUNDS="$2"; shift 2 ;;
    --out-dir)    [[ $# -ge 2 ]] || die "--out-dir requires a value";    OUT_DIR="$2";    shift 2 ;;
    -h|--help)    usage ;;
    *)            die "unknown argument: $1 (try --help)" ;;
  esac
done

START_SECONDS=${SECONDS}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
step "Preflight"

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PY="${REPO_ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  die "No Python interpreter found. Run ./scripts/install.sh first."
fi
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

PY_VERSION="$("${PY}" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
ok "python      : ${PY} (${PY_VERSION})"

"${PY}" -c 'import openai, yaml' 2>/dev/null \
  || die "Missing dependencies. Run ./scripts/install.sh first."
ok "dependencies: openai + PyYAML import OK"

if command -v rg >/dev/null 2>&1; then
  RG_STATUS="found"
  ok "ripgrep     : $(rg --version | head -n1)"
else
  RG_STATUS="missing"
  warn "ripgrep (rg) not found. Offline runs are unaffected, but LLM runs will"
  warn "lose the 'gnu.rg' evidence source. Install it with 'brew install ripgrep'"
  warn "or 'sudo apt-get install -y ripgrep'."
fi

[[ -d "${TARGET_REPO}" ]] || die "Example target repository missing: ${TARGET_REPO}"
[[ -f "${SOURCE_RULES}" ]] || die "Source rules missing: ${SOURCE_RULES}"
[[ -f "${SINK_RULES}" ]]   || die "Sink rules missing:   ${SINK_RULES}"
ok "inputs      : $(basename "${TARGET_REPO}"), 1 source + 1 sink"

mkdir -p "${OUT_DIR}"

run_analysis() {
  local out_file="$1"; shift
  "${PY}" -m semscan.main \
    --repo-root "${TARGET_REPO}" \
    --language python \
    --source-file "${SOURCE_RULES}" \
    --sink-file "${SINK_RULES}" \
    --dotenv "${DOTENV_FILE}" \
    --out "${out_file}" "$@"
}

# ---------------------------------------------------------------------------
# Phase 1 - offline pipeline
# ---------------------------------------------------------------------------
step "Phase 1/2 - offline pipeline (no API key, deterministic)"

OFFLINE_REPORT="${OUT_DIR}/report_offline.json"
rm -f "${OFFLINE_REPORT}"

if ! run_analysis "${OFFLINE_REPORT}" --no-llm > "${OUT_DIR}/offline.log" 2>&1; then
  tail -n 30 "${OUT_DIR}/offline.log" >&2
  die "Offline run failed. Full log: ${OUT_DIR}/offline.log"
fi
ok "run finished -> ${OFFLINE_REPORT}"

"${PY}" "${SCRIPT_DIR}/check_report.py" "${OFFLINE_REPORT}" --mode offline \
  || die "Offline report did not match expectations."

# ---------------------------------------------------------------------------
# Phase 2 - LLM planner
# ---------------------------------------------------------------------------
step "Phase 2/2 - LLM-assisted analysis"

if [[ ${SKIP_LLM} -eq 1 ]]; then
  warn "skipped (--skip-llm)"
  LLM_STATUS="skipped (--skip-llm)"
  LLM_VERDICT="-"
else
  LLM_REPORT="${OUT_DIR}/report_llm.json"
  rm -f "${LLM_REPORT}"

  set +e
  run_analysis "${LLM_REPORT}" --max-rounds "${MAX_ROUNDS}" > "${OUT_DIR}/llm.log" 2>&1
  rc=$?
  set -e

  if [[ ${rc} -eq 0 ]]; then
    ok "run finished -> ${LLM_REPORT}"
    "${PY}" "${SCRIPT_DIR}/check_report.py" "${LLM_REPORT}" --mode llm \
      || die "LLM report did not match expectations."
    LLM_VERDICT="$("${PY}" -c \
      'import json,sys; print(json.load(open(sys.argv[1]))["synthesis"].get("reachable"))' \
      "${LLM_REPORT}")"
    LLM_STATUS="passed"
  elif [[ ${rc} -eq 3 ]]; then
    sed -n '1,4p' "${OUT_DIR}/llm.log" | sed 's/^/  /'
    warn "no API key configured, so the LLM phase was skipped"
    warn "to enable it: cp config.env .env   # then set PLANNER_API_KEY"
    LLM_STATUS="skipped (no API key)"
    LLM_VERDICT="-"
  else
    tail -n 30 "${OUT_DIR}/llm.log" >&2
    die "LLM run failed with exit code ${rc}. Full log: ${OUT_DIR}/llm.log"
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
ELAPSED=$(( SECONDS - START_SECONDS ))

if [[ -f "${DOTENV_FILE}" ]]; then
  DOTENV_STATUS="found"
else
  DOTENV_STATUS="not found"
fi

printf '\n\033[1;32mKick-the-tires completed\033[0m\n\n'
cat <<EOF
  python        : ${PY} (${PY_VERSION})
  ripgrep       : ${RG_STATUS}
  env file      : ${DOTENV_FILE} (${DOTENV_STATUS})
  offline phase : passed   -> ${OFFLINE_REPORT}
  llm phase     : ${LLM_STATUS}
  llm verdict   : ${LLM_VERDICT}
  elapsed       : ${ELAPSED}s
  logs          : ${OUT_DIR}/

EOF
