# SemScan

SemScan is a repository-level vulnerability analysis prototype for source-to-sink reachability inspection. It combines lightweight repository tooling, static hints, and optional LLM-based planning/synthesis to produce a structured JSON report.

## What It Does

SemScan takes:

- a target repository root,
- a programming language,
- a source rule file,
- a sink rule file,

and produces a report describing local evidence, intermediate reasoning context, and a final reachability judgment.

The current implementation under `src/semscan` follows a multi-stage flow:

1. parse source/sink locations from `jsonl` or `yaml`,
2. build a repository map and analyze each source/sink locally,
3. let the planner propose extra evidence-collection steps when LLMs are enabled,
4. synthesize all evidence into a final JSON report.

## Repository Layout

```text
SemScan/
├── src/semscan/          # core implementation
├── rules/                # example source/sink rule files
├── scripts/              # helper scripts
├── CVE-2023-6730/        # example target repository / benchmark material
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

SemScan reads `.env` through `--dotenv` (default: `.env`). Typical fields are:

- `PLANNER_API_KEY`, `PLANNER_BASE_URL`, `PLANNER_MODEL`
- `WORKER_API_KEY`, `WORKER_BASE_URL`, `WORKER_MODEL`
- or fallback `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`

If you do not want any LLM calls, run with `--no-llm`.

## Test Drive (kick the tires)

`scripts/kick_the_tires.sh` runs a minimal end-to-end analysis against the
bundled example: `CVE-2023-6730`, an unsafe `pickle.load` in the RAG retriever of
transformers 4.35.2, declared through one source and one sink. On a laptop the
whole thing takes roughly two minutes.

```bash
./scripts/kick_the_tires.sh
```

The script runs two phases:

| Phase | API key needed | What it verifies |
| --- | --- | --- |
| 1. Offline | no | Rule parsing, repository traversal, AST lookup, file reading, evidence extraction and report assembly (`--no-llm`) |
| 2. LLM | yes | Planner/worker LLM calls, token accounting and the final reachability verdict |

Phase 2 is **skipped automatically** when no API key is configured, so the script
is safe to run before a provider has been set up.

Options:

```bash
./scripts/kick_the_tires.sh --skip-llm       # offline phase only
./scripts/kick_the_tires.sh --max-rounds 3   # more planner rounds
DOTENV_FILE=/path/to/other.env ./scripts/kick_the_tires.sh
```

Outputs are written to `kick_the_tires_out/`:

- `report_offline.json`, `report_llm.json` — the generated reports
- `offline.log`, `llm.log` — the full run logs

A successful run ends like this:

```text
all 26 checks passed

Kick-the-tires completed

  python        : /path/to/SemScan/.venv/bin/python (3.11.9)
  ripgrep       : found
  env file      : /path/to/SemScan/.env (found)
  offline phase : passed   -> /path/to/SemScan/kick_the_tires_out/report_offline.json
  llm phase     : passed
  llm verdict   : yes
  elapsed       : 101s
```

What each phase actually asserts:

- **Offline phase (deterministic).** The report must contain the two expected
  locations, must have discovered the repository, must carry evidence whose text
  really is the source and sink lines, and must report `reachable: "unknown"`.
  This is what proves the environment and the analysis pipeline are wired up
  correctly.
- **LLM phase (non-deterministic).** The run must make planner and worker calls,
  must report token usage, and must produce a verdict. The verdict itself is
  deliberately **not** asserted. The bundled example is a true positive, but with
  the default single planner round the model sometimes answers
  `reachable: "yes"` and sometimes `reachable: "unknown"`, listing explicit gaps
  it could not close in time.

Give the planner more rounds if you want it to have a better chance of closing
those gaps:

```bash
./scripts/kick_the_tires.sh --max-rounds 3
```

> If `ripgrep` is missing, the offline phase still passes; only phase 2 loses the
> `gnu.rg` evidence source.

## Rule File Formats

SemScan currently accepts `jsonl` and `yaml` rule files. In one run, the source file and sink file should use the same format.

Example `jsonl`:

```jsonl
{"path": "src/transformers/models/rag/retrieval_rag.py", "line": 419, "symbol": "retriever_name_or_path", "snippet": "", "note": ""}
{"path": "src/transformers/models/rag/retrieval_rag.py", "line": 306, "symbol": "dataset_path", "snippet": "", "note": ""}
```

Example `yaml`:

```yaml
lang: python
rules:
  - path: src/transformers/models/rag/retrieval_rag.py
    line: 419
    symbol: retriever_name_or_path
  - path: src/transformers/models/rag/retrieval_rag.py
    line: 306
    symbol: dataset_path
```

## Running SemScan

Run the CLI directly:

```bash
PYTHONPATH=src python -m semscan.main \
  --repo-root /path/to/target-repo \
  --language python \
  --source-file ./rules/sources.jsonl \
  --sink-file ./rules/sinks.jsonl \
  --out ./report.json
```

Common options:

- `--out`: output report path, default `report.json`
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

You can also use the helper script:

```bash
./scripts/analyze.sh /path/to/target-repo python
```

With extra options:

```bash
./scripts/analyze.sh /path/to/target-repo python ./rules/sources.jsonl ./rules/sinks.jsonl report.json --no-llm
./scripts/analyze.sh /path/to/target-repo python report.json --dotenv .env --max-rounds 3
```

If explicit rules are omitted, `scripts/analyze.sh` will look for:

- `./rules/source.yaml` and `./rules/sink.yaml`, or
- `./rules/sources.jsonl` and `./rules/sinks.jsonl`

When explicit rule files are provided, they must both be `.jsonl` or both be `.yaml`.

## Architecture Notes

- `src/semscan/main.py`: CLI entrypoint
- `src/semscan/orchestrator.py`: end-to-end flow orchestration
- `src/semscan/planner.py`: main planning/synthesis agent
- `src/semscan/agents/worker.py`: worker agent for repo map, local context, and step summaries
- `src/semscan/skills/`: executable analysis tools and registry/pipeline logic

In `--no-llm` mode, SemScan still parses inputs and runs the repository/tooling pipeline, but the final synthesis is reported as `unknown` instead of using planner reasoning.

## Example Rules And Benchmark Material

The repository already includes example rule files here:

- `rules/sources.jsonl`
- `rules/sinks.jsonl`

The repository also includes example benchmark/target material here:

- `CVE-2023-6730/transformers-4.35.2/`

If you specifically want benchmark-related subdirectories inside that example repository, see:

- `CVE-2023-6730/transformers-4.35.2/scripts/benchmark`
- `CVE-2023-6730/transformers-4.35.2/tests/benchmark`

## Output

The main output is a JSON report, typically written to `report.json`. It includes:

- repository metadata,
- normalized source/sink inputs,
- preprocessing findings,
- extra pipeline evidence collected during synthesis rounds,
- the final reachability result.
