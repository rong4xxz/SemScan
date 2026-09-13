#!/usr/bin/env bash
#
# SemScan one-shot installer.
#
# Creates a Python virtual environment in .venv, installs SemScan together with
# its dependencies, and verifies the external tools SemScan relies on.
#
# Examples:
#   ./scripts/install.sh
#   PYTHON_BIN=python3.11 ./scripts/install.sh
#   VENV_DIR=.venv-py311   ./scripts/install.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${VENV_DIR:-${REPO_ROOT}/.venv}"
MIN_MINOR=9

log()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[install] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Accept Python 3.9 and newer. "$1" is a "major.minor" string.
python_ok() {
  local major minor
  major="${1%%.*}"
  minor="${1#*.}"
  minor="${minor%%.*}"
  [[ "${major}" =~ ^[0-9]+$ ]] || return 1
  [[ "${minor}" =~ ^[0-9]+$ ]] || return 1
  if (( major > 3 )); then return 0; fi
  if (( major == 3 && minor >= MIN_MINOR )); then return 0; fi
  return 1
}

find_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    command -v "${PYTHON_BIN}" >/dev/null 2>&1 \
      || { warn "PYTHON_BIN='${PYTHON_BIN}' was not found on PATH."; return 1; }
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  local cand ver
  for cand in python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
    command -v "${cand}" >/dev/null 2>&1 || continue
    ver="$("${cand}" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
    if [[ -n "${ver}" ]] && python_ok "${ver}"; then
      printf '%s\n' "${cand}"
      return 0
    fi
  done
  return 1
}

log "SemScan installer"
log "repository : ${REPO_ROOT}"

PYTHON="$(find_python)" || die "No Python >= 3.${MIN_MINOR} found.
  macOS        : brew install python@3.11
  Debian/Ubuntu: sudo apt-get install -y python3.11 python3.11-venv
  or set PYTHON_BIN=/path/to/python3 and retry."

PY_VERSION="$("${PYTHON}" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
log "python     : ${PYTHON} (${PY_VERSION})"

if [[ -d "${VENV_DIR}" ]]; then
  log "venv       : reusing ${VENV_DIR}"
else
  log "venv       : creating ${VENV_DIR}"
  "${PYTHON}" -m venv "${VENV_DIR}" \
    || die "Could not create a virtual environment. On Debian/Ubuntu install 'python3-venv'."
fi

VENV_PY="${VENV_DIR}/bin/python"
[[ -x "${VENV_PY}" ]] || die "Expected an interpreter at ${VENV_PY}, but it does not exist."

log "installing : upgrading pip"
"${VENV_PY}" -m pip install --upgrade pip

log "installing : semscan (editable) + requirements.txt"
( cd "${REPO_ROOT}" && "${VENV_PY}" -m pip install -e . -r requirements.txt )

# ---------------------------------------------------------------------------
# External tool check. ripgrep is required by the gnu.rg skill, which the LLM
# planner may select. It is not needed for --no-llm runs, so a miss is a warning.
# ---------------------------------------------------------------------------
if command -v rg >/dev/null 2>&1; then
  RG_STATUS="found ($(rg --version | head -n1))"
  log "ripgrep    : ${RG_STATUS}"
else
  RG_STATUS="MISSING"
  warn "ripgrep (rg) was not found on PATH."
  warn "  The 'gnu.rg' tool needs it. Offline (--no-llm) runs work without it,"
  warn "  but LLM-backed runs silently lose that evidence source."
  warn "    macOS (Homebrew) : brew install ripgrep"
  warn "    Debian / Ubuntu  : sudo apt-get install -y ripgrep"
  warn "    other platforms  : https://github.com/BurntSushi/ripgrep#installation"
fi

# ---------------------------------------------------------------------------
# Dependency self-check.
# ---------------------------------------------------------------------------
"${VENV_PY}" -c 'import openai, yaml' \
  || die "Dependency check failed: 'openai' and/or 'PyYAML' could not be imported."
log "verify     : 'import openai, yaml' OK"

cat <<EOF

SemScan installed successfully.

  virtualenv : ${VENV_DIR}
  interpreter: ${VENV_PY}
  ripgrep    : ${RG_STATUS}

Next steps

  1) Activate the environment:

       source ${VENV_DIR}/bin/activate

  2) (optional) Configure an LLM provider. Without this, only offline
     (--no-llm) runs are possible:

       cp config.env .env     # then edit .env and set PLANNER_API_KEY

  3) Run the smoke test. It needs no API key and finishes in seconds:

       ./scripts/kick_the_tires.sh

EOF
