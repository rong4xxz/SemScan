# SemScan

SemScan is a repository-level vulnerability analysis prototype for source-to-sink reachability inspection. It combines lightweight repository tooling, static hints, and optional LLM-based planning/synthesis to produce a structured JSON report.

## What It Does

SemScan takes:

- a target repository root,
- a source rule file,
- a sink rule file,

and produces a report describing local evidence, intermediate reasoning context, and a final reachability judgment. The analysis targets Python repositories: the static tooling is built on Python's own `ast` module.

The current implementation under `src/semscan` follows a multi-stage flow:

1. parse source/sink locations from `jsonl` or `yaml`,
2. build a repository map and analyze each source/sink locally,
3. let the planner propose extra evidence-collection steps when LLMs are enabled,
4. synthesize all evidence into a final JSON report.

## Repository Layout

```text
SemScan/
├── src/semscan/                     # core implementation
├── scripts/                         # installer, single-case runner, batch driver
├── rules/
│   ├── bench.jsonl                  # manifest: one entry per benchmark CVE
│   └── bench/<CVE>/
│       ├── source.jsonl             # source rules
│       └── sink.jsonl               # sink rules
├── benchmark/<CVE>/<repo>/          # target repositories (30 CVEs)
├── config.env                       # environment template
├── requirements.txt
├── pyproject.toml
└── README.md
```

## System Requirements

| Item | Requirement |
| --- | --- |
| Operating system | Linux or macOS (any POSIX-like system with a `bash` shell) |
| Python | **3.9 or newer** (3.10+ recommended; verified on 3.9 and 3.10+) |
| Python packages | `openai` and `PyYAML`, installed from `requirements.txt` |
| External binary | [`ripgrep`](https://github.com/BurntSushi/ripgrep) (`rg`) available on `PATH` |
| CPU / RAM | Any x86-64 or arm64 CPU; 2 cores and 4 GB RAM are sufficient |
| GPU | **Not required.** SemScan is pure CPU: it performs file, AST and text analysis locally and calls a remote LLM over HTTP. It does not import `torch`, `tensorflow`, or any CUDA runtime. |
| Disk space | ~200 MB (source code plus the bundled example target repository `CVE-2023-6730/`, ~70 MB) |
| Network | Only required for LLM calls. `--no-llm` runs fully offline. |

### About the `ripgrep` dependency

The `gnu.rg` skill shells out to `ripgrep`, and the planner may select that tool
during a run. If `rg` is missing, SemScan does **not** abort: the affected
pipeline step records an error and the run continues with less evidence.

`--no-llm` runs never use `gnu.rg`, so `ripgrep` is only required for LLM-backed runs.

```bash
# macOS (Homebrew)
brew install ripgrep

# Debian / Ubuntu
sudo apt-get install -y ripgrep

# other platforms: https://github.com/BurntSushi/ripgrep#installation
```

## Installation

### One-shot installer (recommended)

```bash
./scripts/install.sh
```

This selects a suitable Python (>= 3.9), creates `.venv`, installs SemScan and
its dependencies, checks for `ripgrep`, and verifies that the dependencies
import. Override the interpreter or the environment location if needed:

```bash
PYTHON_BIN=python3.11 ./scripts/install.sh
VENV_DIR=.venv-py311  ./scripts/install.sh
```

### Manual installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . -r requirements.txt
```

> Both install targets are needed: `pyproject.toml` declares only `openai`, while
> `PyYAML` lives in `requirements.txt`. Installing only one of them leaves
> SemScan unable to parse `.yaml` rule files.

## Configuration

Copy the template and fill in your model settings:

```bash
cp config.env .env
```

SemScan reads `.env` through `--dotenv` (default: `.env`). Three groups of
variables are recognised:

| Variables | Used by | Fallback when unset |
| --- | --- | --- |
| `PLANNER_API_KEY`, `PLANNER_BASE_URL`, `PLANNER_MODEL` | main planning / synthesis agent | `OPENAI_*`, then the defaults `https://api.openai.com/v1` and `gpt-4o-mini` |
| `WORKER_API_KEY`, `WORKER_BASE_URL`, `WORKER_MODEL` | worker agent (repository map, per-location analysis, step summaries) | **inherits the resolved planner values** |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | compatibility alias for the planner | — |

### What happens if the `WORKER_*` variables are unset

**The worker agent still runs.** It is neither disabled nor reported as an
error: each unset `WORKER_*` value falls back to the corresponding planner
value, so both agents end up sharing one key, endpoint and model.

```python
worker_key   = os.getenv("WORKER_API_KEY")   or api_key    # planner key
worker_base  = os.getenv("WORKER_BASE_URL")  or base_url   # planner base URL
worker_model = os.getenv("WORKER_MODEL")     or model      # planner model
```

Set a `WORKER_*` variable only when you want the worker to use a different
(typically cheaper) model, for example:

```bash
PLANNER_MODEL=deepseek-reasoner
WORKER_MODEL=deepseek-chat
```

A key is still mandatory: with neither `PLANNER_API_KEY` nor `OPENAI_API_KEY`
set, the run stops with a configuration error (exit code `3`) regardless of the
worker variables.

If you do not want any LLM calls, run with `--no-llm`. In that mode neither
agent is created and `synthesis.reachable` is reported as `unknown`.

## Test Drive

The quickest way to verify the environment is to run the batch driver on a single
benchmark entry. It needs no API key and finishes in seconds:

```bash
python scripts/batch_analyze.py --limit 1 --no-llm
```

This reads `rules/bench.jsonl`, takes the first entry, and runs it twice (every
CVE is run twice by design). Reports land in `result/batch/<timestamp>/`,
next to an aggregate `summary.json`:

```text
[batch] CVE-2023-29374 => 2 runs (repo_root=.../benchmark/CVE-2023-29374/langchain-0.0.131)
[batch] 总共 2 个任务，并发度 4
[batch] [1/2] CVE-2023-29374_single_1 completed
[batch] [2/2] CVE-2023-29374_single_2 completed
[batch] done. summary => .../result/batch/20260915_111944/summary.json
```

Each run records a small health record, so you can see what was actually produced
without opening every report:

```json
"ok": true,
"exit_code": 0,
"report_health": {
  "no_llm": true,
  "local_findings": 2,
  "evidence_total": 2,
  "reachable": "unknown"
}
```

`local_findings > 0` together with `evidence_total > 0` means the pipeline really
parsed the rules, walked the repository, and extracted source code as evidence.
Under `--no-llm` a `"reachable": "unknown"` verdict is expected: offline mode
performs no synthesis by design.

To exercise the LLM path as well, configure a key and drop `--no-llm`:

```bash
cp config.env .env      # then set PLANNER_API_KEY
python scripts/batch_analyze.py --limit 1
```

That takes a few minutes and yields a real verdict. LLM output is
non-deterministic, so the verdict and the wording of the summary vary between
runs.

> `--limit 1` uses the first entry of the manifest. Use `--limit N` for more
> entries, or `--experiment FILE` to point at a different manifest.

To run a single case with explicit paths instead of the manifest, use
`scripts/analyze.sh` (see below).

## Rule File Formats

SemScan currently accepts `jsonl` and `yaml` rule files. In one run, the source file and sink file should use the same format. The benchmark ships `jsonl` rules only.

`path` is relative to the analyzed repository root.

Example — `rules/bench/CVE-2023-6730/source.jsonl`:

```jsonl
{"path": "src/transformers/models/rag/retrieval_rag.py", "line": 419, "symbol": "retriever_name_or_path", "snippet": null, "note": null}
```

Example `yaml`:

```yaml
lang: python
rules:
  - path: src/transformers/models/rag/retrieval_rag.py
    line: 419
    symbol: retriever_name_or_path
```

## Running SemScan

Run the CLI directly:

```bash
PYTHONPATH=src python -m semscan.main \
  --repo-root ./benchmark/CVE-2023-6730/transformers-4.35.2 \
  --source-file ./rules/bench/CVE-2023-6730/source.jsonl \
  --sink-file ./rules/bench/CVE-2023-6730/sink.jsonl \
  --out ./report.json
```

Common options:

- `--repo-root`: repository to analyze (required)
- `--source-file`, `--sink-file`: rule files (required)
- `--out`: output report path, default `report.json`
- `--language`: analysis language, default `python`
- `--dotenv`: env file path, default `.env`
- `--max-rounds`: maximum planner/synthesis rounds, default `5`
- `--no-llm`: disable planner/worker LLM calls

### LLM mode requires an API key

Without `--no-llm`, SemScan requires a usable API key. If none is configured, the
run **fails immediately with a non-zero exit code** instead of silently degrading
to an offline report:

```text
[semscan] configuration error
[semscan]   LLM mode is enabled but no API key was found. Set PLANNER_API_KEY
(or OPENAI_API_KEY) in '.env' (see config.env for a template), or pass --no-llm
to run fully offline.
```

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Run completed and a report was written |
| `2` | Unexpected runtime failure (a traceback is printed) |
| `3` | Invalid configuration, e.g. LLM mode enabled without an API key |

### Single-case helper script

`scripts/analyze.sh` wraps the CLI with sensible defaults. Without further
options it uses the bundled example rules
(`rules/bench/CVE-2023-6730/source.jsonl` and `sink.jsonl`) and writes to
`result/single/<timestamp>/report.json`:

```bash
./scripts/analyze.sh ./benchmark/CVE-2023-6730/transformers-4.35.2 --no-llm
```

Point it at other rules and an output path with `--source`, `--sink` and `--out`:

```bash
./scripts/analyze.sh ./benchmark/CVE-2023-51449/gradio-4.10.0 \
  --source ./rules/bench/CVE-2023-51449/source.jsonl \
  --sink   ./rules/bench/CVE-2023-51449/sink.jsonl \
  --out    ./result/single/gradio.json \
  --no-llm
```

Other options: `--dotenv FILE`, `--max-rounds N`, `--no-llm`, `-h`.

The two rule files must use the same format: both `.jsonl` or both `.yaml`.

## Architecture Notes

- `src/semscan/main.py`: CLI entrypoint
- `src/semscan/orchestrator.py`: end-to-end flow orchestration
- `src/semscan/planner.py`: main planning/synthesis agent
- `src/semscan/agents/worker.py`: worker agent for repo map, local context, and step summaries
- `src/semscan/skills/`: executable analysis tools and registry/pipeline logic

In `--no-llm` mode, SemScan still parses inputs and runs the repository/tooling pipeline, but the final synthesis is reported as `unknown` instead of using planner reasoning.

## Benchmark Material

The benchmark ships **30 CVEs**, laid out as:

```text
benchmark/<CVE>/<repo>/                # target repository
rules/bench/<CVE>/source.jsonl         # source rules
rules/bench/<CVE>/sink.jsonl           # sink rules
```

`rules/bench.jsonl` is the manifest: one JSON object per CVE, holding the
repository path and the two rule paths.

```jsonl
{"index": "CVE-2023-6730", "repo_path": "benchmark/CVE-2023-6730/transformers-4.35.2", "source": "rules/bench/CVE-2023-6730/source.jsonl", "sink": "rules/bench/CVE-2023-6730/sink.jsonl"}
```

All paths are relative to the repository root. Blank lines and lines starting
with `//` or `#` are ignored, so an entry can be disabled without deleting it.

### Batch experiment driver

`scripts/batch_analyze.py` reads `rules/bench.jsonl` and turns every entry into a
task. Each CVE is run **twice** (two independent attempts), using a thread pool
and per-run retries:

```bash
python scripts/batch_analyze.py --out-dir out --concurrency 4
```

Useful options: `--limit N` (only the first N entries), `--no-llm`,
`--max-rounds N`, `--retries N`, `--timeout-s N`, `--benchmark-root DIR`.

Results are written to `<out-dir>/<CVE>/<CVE>_single_<n>.json`, next to the
matching `.stdout.txt` and `.stderr.txt`, plus an aggregate
`<out-dir>/summary.json`.

## Output

The main output is a JSON report, typically written to `report.json`. It includes:

- repository metadata,
- normalized source/sink inputs,
- preprocessing findings,
- extra pipeline evidence collected during synthesis rounds,
- the final reachability result.
