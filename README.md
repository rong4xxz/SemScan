# OmniVul

Multi-agent (Skills + LLM) code dataflow analysis tool. Traces data flow from user-defined sources to sinks (e.g., SQL execution, code execution) in a target repository.

## Requirements

- Python >= 3.10
- See `requirements.txt` for dependencies

## 1. Environment Setup

```bash
cd PROJECT_ROOT
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Input File Format (JSONL)

Source and sink files are JSONL: one JSON object per line.

**Example `sources.jsonl`:**

```jsonl
{"path":"src/app.py","line":12,"symbol":"user_input","snippet":null,"note":null}
```

**Example `sinks.jsonl`:**

```jsonl
{"path":"src/app.py","line":48,"symbol":"cursor.execute","snippet":"cursor.execute(sql)","note":"execute the sql query"}
```

Fields: `path`, `line`, `symbol`, `snippet` (optional), `note` (optional).

## 3. Run

### Shell script (no install)

```bash
chmod +x scripts/analyze.sh
./scripts/analyze.sh /path/to/repo -l python -source source.jsonl -sink sink.jsonl
```

Optional: `-o report.json` to set the output report path (default: `report.json`).

Optional: `--out report.json`, `--no-llm` (offline), `--dotenv .env`, `--max-rounds 5`.

## 4. Output

The tool writes a JSON report (default: `report.json`) with reachability, summary, paths, and related findings.
