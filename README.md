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

## Environment Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r requirements.txt
```

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
