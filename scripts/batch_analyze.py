from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _load_jsonl_lines(p: Path) -> List[Tuple[int, str]]:
    lines: List[Tuple[int, str]] = []
    raw = p.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(raw, start=1):
        s = line.strip()
        # Skip blank lines and comments. Both "#" and "//" are accepted because
        # the benchmark manifests disable individual entries with "//".
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        lines.append((i, s))
    return lines


def _resolve_against_root(root: Path, maybe_path: str) -> Path:
    p = Path(maybe_path)
    if p.is_absolute():
        return p
    return (root / p).resolve()


def _resolve_repo_path(root: Path, benchmark_root: Path, maybe_path: str) -> str:
    """Resolve a manifest ``repo_path`` to a local directory.

    Manifests are generated on a machine where repositories live under an
    absolute ``.../benchmark/<CVE>/<repo>`` path. Three cases are supported:

    * a relative path is resolved against the repository root, for example
      ``benchmark/CVE-2023-6730/transformers-4.35.2``
    * an absolute path that exists locally is used unchanged
    * an absolute path that does not exist here is re-rooted on the local
      benchmark directory using its trailing ``benchmark/<CVE>/<repo>`` part
    """
    p = Path(maybe_path)
    if not p.is_absolute():
        return str(_resolve_against_root(root, maybe_path))
    if p.is_dir():
        return str(p)
    parts = p.parts
    if "benchmark" in parts:
        tail = Path(*parts[parts.index("benchmark") + 1:])
        return str((benchmark_root / tail).resolve())
    return str(p)


@dataclass(frozen=True)
class RunSpec:
    index: str
    repo_root: str
    mode: str  # "single"
    attempt: int  # 1 | 2
    source_file: str
    sink_file: str

    @property
    def run_id(self) -> str:
        return f"{self.index}_{self.mode}_{self.attempt}"


def _build_cmd(
    *,
    python_exe: str,
    repo_root: str,
    language: str,
    source_file: str,
    sink_file: str,
    out_file: str,
    dotenv: str,
    no_llm: bool = False,
    max_rounds: int = 5,
) -> List[str]:
    cmd = [
        python_exe,
        "-m",
        "semscan.main",
        "--repo-root",
        repo_root,
        "--language",
        language,
        "--source-file",
        source_file,
        "--sink-file",
        sink_file,
        "--out",
        out_file,
        "--dotenv",
        dotenv,
        "--max-rounds",
        str(max_rounds),
    ]
    if no_llm:
        cmd.append("--no-llm")
    return cmd


def _run_once(
    *,
    root_path: Path,
    run: RunSpec,
    out_dir: Path,
    dotenv: str,
    timeout_s: Optional[float],
    no_llm: bool = False,
    max_rounds: int = 5,
) -> Dict[str, Any]:
    """
    执行一次分析，返回结构化结果（不抛异常；异常会被编码到返回值中）。
    """
    index_dir = out_dir / run.index
    _safe_mkdir(index_dir)
    out_path = (index_dir / f"{run.run_id}.json").resolve()
    stdout_path = (index_dir / f"{run.run_id}.stdout.txt").resolve()
    stderr_path = (index_dir / f"{run.run_id}.stderr.txt").resolve()

    repo_root_p = Path(run.repo_root)
    src_p = Path(run.source_file)
    sink_p = Path(run.sink_file)

    # 预检查：缺文件就不启动子进程（这类算"失败"，但更快、更可控）
    precheck_errors: List[str] = []
    if not repo_root_p.exists():
        precheck_errors.append(f"repo_root 不存在: {run.repo_root}")
    if not src_p.exists():
        precheck_errors.append(f"source_file 不存在: {run.source_file}")
    if not sink_p.exists():
        precheck_errors.append(f"sink_file 不存在: {run.sink_file}")

    started_at = _now_iso()
    t0 = time.perf_counter()

    if precheck_errors:
        dt = time.perf_counter() - t0
        return {
            "run_id": run.run_id,
            "index": run.index,
            "mode": run.mode,
            "attempt": run.attempt,
            "repo_root": run.repo_root,
            "source_file": run.source_file,
            "sink_file": run.sink_file,
            "out_file": str(out_path),
            "stdout_file": str(stdout_path),
            "stderr_file": str(stderr_path),
            "started_at": started_at,
            "duration_s": dt,
            "ok": False,
            "exit_code": None,
            "error": "precheck_failed",
            "details": precheck_errors,
        }

    cmd = _build_cmd(
        python_exe=sys.executable,
        repo_root=run.repo_root,
        language="python",
        source_file=run.source_file,
        sink_file=run.sink_file,
        out_file=str(out_path),
        dotenv=dotenv,
        no_llm=no_llm,
        max_rounds=max_rounds,
    )

    # 关键：让 PYTHONPATH 指向 ROOT/src，使 example 可被导入
    env = os.environ.copy()
    root_src = str((root_path / "src").resolve())
    prev_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root_src if not prev_pp else (root_src + os.pathsep + prev_pp)

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root_path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
        ok = proc.returncode == 0
        dt = time.perf_counter() - t0

        # Summarise what the report actually contains. An exit code of 0 alone
        # does not prove that the pipeline produced anything useful, so every
        # run carries a small health record into summary.json.
        token_usage = None
        report_health: Optional[Dict[str, Any]] = None
        if out_path.exists():
            try:
                report_obj = json.loads(out_path.read_text(encoding="utf-8", errors="replace"))
                meta = report_obj.get("meta") or {}
                synthesis = report_obj.get("synthesis") or {}
                findings = report_obj.get("local_findings") or []
                token_usage = meta.get("token_usage")
                report_health = {
                    "no_llm": meta.get("no_llm"),
                    "local_findings": len(findings),
                    "evidence_total": sum(
                        len(f.get("evidence") or []) for f in findings if isinstance(f, dict)
                    ),
                    "reachable": synthesis.get("reachable") if isinstance(synthesis, dict) else None,
                }
            except Exception as e:
                report_health = {"error": f"{type(e).__name__}: {e}"}

        if ok and report_health and report_health.get("local_findings") == 0:
            print(f"[batch]   ! {run.run_id}: exit 0 but the report has no local findings")

        return {
            "run_id": run.run_id,
            "index": run.index,
            "mode": run.mode,
            "attempt": run.attempt,
            "repo_root": run.repo_root,
            "source_file": run.source_file,
            "sink_file": run.sink_file,
            "out_file": str(out_path),
            "stdout_file": str(stdout_path),
            "stderr_file": str(stderr_path),
            "cmd": cmd,
            "started_at": started_at,
            "duration_s": dt,
            "ok": ok,
            "exit_code": proc.returncode,
            "token_usage": token_usage,
            "report_health": report_health,
        }
    except subprocess.TimeoutExpired as e:
        dt = time.perf_counter() - t0
        # subprocess.TimeoutExpired 的 stdout/stderr 字段可能是 bytes/str
        so = e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, (bytes, bytearray)) else (e.stdout or "")
        se = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, (bytes, bytearray)) else (e.stderr or "")
        stdout_path.write_text(so, encoding="utf-8", errors="replace")
        stderr_path.write_text(se, encoding="utf-8", errors="replace")
        return {
            "run_id": run.run_id,
            "index": run.index,
            "mode": run.mode,
            "attempt": run.attempt,
            "repo_root": run.repo_root,
            "source_file": run.source_file,
            "sink_file": run.sink_file,
            "out_file": str(out_path),
            "stdout_file": str(stdout_path),
            "stderr_file": str(stderr_path),
            "cmd": cmd,
            "started_at": started_at,
            "duration_s": dt,
            "ok": False,
            "exit_code": None,
            "error": "timeout",
            "details": {"timeout_s": timeout_s},
        }
    except Exception as e:
        dt = time.perf_counter() - t0
        stderr_path.write_text(str(e), encoding="utf-8", errors="replace")
        return {
            "run_id": run.run_id,
            "index": run.index,
            "mode": run.mode,
            "attempt": run.attempt,
            "repo_root": run.repo_root,
            "source_file": run.source_file,
            "sink_file": run.sink_file,
            "out_file": str(out_path),
            "stdout_file": str(stdout_path),
            "stderr_file": str(stderr_path),
            "started_at": started_at,
            "duration_s": dt,
            "ok": False,
            "exit_code": None,
            "error": "exception",
            "details": {"type": type(e).__name__, "message": str(e)},
        }


def _run_with_retries(
    *,
    root_path: Path,
    run: RunSpec,
    out_dir: Path,
    dotenv: str,
    timeout_s: Optional[float],
    retries: int,
    retry_backoff_s: float,
    no_llm: bool = False,
    max_rounds: int = 5,
) -> List[Dict[str, Any]]:
    """
    执行一次运行（带重试），返回所有尝试的结果列表。
    """
    attempts_total = 1 + max(0, int(retries))
    results: List[Dict[str, Any]] = []
    
    for k in range(attempts_total):
        r = _run_once(
            root_path=root_path,
            run=run,
            out_dir=out_dir,
            dotenv=dotenv,
            timeout_s=timeout_s,
            no_llm=no_llm,
            max_rounds=max_rounds,
        )
        r["try"] = k + 1
        r["tries_total"] = attempts_total
        results.append(r)

        if r.get("ok") is True:
            break

        if k + 1 < attempts_total:
            sleep_s = float(retry_backoff_s) * float(k + 1)
            print(f"[batch]   - {run.run_id} try {k+1}/{attempts_total} failed; retry in {sleep_s:.1f}s")
            time.sleep(sleep_s)
        else:
            print(f"[batch]   - {run.run_id} try {k+1}/{attempts_total} failed; give up")
    
    return results


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="batch_analyze",
        description="批量运行 semscan：读取 rules/bench.jsonl，每个 CVE 跑两遍并产出报告。支持并发执行。",
    )
    p.add_argument(
        "--experiment",
        default=None,
        help="输入清单 jsonl 路径（默认 ROOT_PATH/rules/bench.jsonl）",
    )
    p.add_argument(
        "--benchmark-root",
        default=None,
        help="benchmark 根目录，用于重定位清单里的仓库路径（默认 ROOT_PATH/benchmark）",
    )
    p.add_argument(
        "--out-dir",
        default=None,
        help="输出目录（默认 ROOT_PATH/result/batch/{时间戳}）",
    )
    p.add_argument(
        "--summary",
        default=None,
        help="汇总 summary.json 路径（默认 OUT_DIR/summary.json）",
    )
    p.add_argument(
        "--dotenv",
        default=".env",
        help="传给 semscan.main 的 --dotenv（默认 .env，以 ROOT_PATH 为 cwd 解析）",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="离线模式：所有任务传 --no-llm 给 semscan.main",
    )
    p.add_argument(
        "--max-rounds",
        type=int,
        default=5,
        help="主 Agent 综合轮数，传给 semscan.main（默认 5）",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=3,
        help="每次运行失败后的重试次数（默认 3；即最多尝试 1+retries 次）",
    )
    p.add_argument(
        "--retry-backoff-s",
        type=float,
        default=2.0,
        help="重试退避基数秒（默认 2.0；第 k 次重试 sleep backoff*k）",
    )
    p.add_argument(
        "--timeout-s",
        type=float,
        default=None,
        help="单次运行超时时间（秒）。不设置则不超时。",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只跑前 N 行有效数据（用于小规模验证）。",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="并发执行的任务数（默认 4，即一次跑 2 条链路，每条链路跑 2 次）",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # ROOT_PATH 由脚本文件的"两级父目录"获得
    # - __file__ = ROOT_PATH/scripts/xxx.py
    # - parents[0] = scripts
    # - parents[1] = ROOT_PATH
    root_path = Path(__file__).resolve().parents[1]
    benchmark_root = (
        _resolve_against_root(root_path, args.benchmark_root)
        if args.benchmark_root
        else (root_path / "benchmark").resolve()
    )

    exp_path = (
        _resolve_against_root(root_path, args.experiment)
        if args.experiment
        else (root_path / "rules" / "bench.jsonl").resolve()
    )
    # 默认：所有 report 输出到 ROOT_PATH/result/batch/{时间戳}
    if args.out_dir:
        out_dir = _resolve_against_root(root_path, args.out_dir)
    else:
        # 生成时间戳：YYYYMMDD_HHMMSS
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = (root_path / "result" / "batch" / timestamp).resolve()
    _safe_mkdir(out_dir)

    # 默认：summary 输出到 OUT_DIR/summary.json
    summary_path = (
        _resolve_against_root(root_path, args.summary)
        if args.summary
        else (out_dir / "summary.json").resolve()
    )
    _safe_mkdir(summary_path.parent)

    no_llm = getattr(args, "no_llm", False)
    max_rounds = getattr(args, "max_rounds", 5)

    summary: Dict[str, Any] = {
        "meta": {
            "root_path": str(root_path),
            "benchmark_root": str(benchmark_root),
            "experiment": str(exp_path),
            "out_dir": str(out_dir),
            "dotenv": args.dotenv,
            "no_llm": no_llm,
            "max_rounds": max_rounds,
            "retries": int(args.retries),
            "retry_backoff_s": float(args.retry_backoff_s),
            "timeout_s": args.timeout_s,
            "concurrency": int(args.concurrency),
            "generated_at": _now_iso(),
        },
        "skipped_lines": [],
        "runs": [],
    }

    try:
        pairs = _load_jsonl_lines(exp_path)
    except Exception as e:
        print(f"[batch] 无法读取清单: {exp_path} ({e})", file=sys.stderr)
        return 2

    # 收集所有需要运行的 RunSpec
    all_run_specs: List[RunSpec] = []
    valid_count = 0
    
    for (lineno, line) in pairs:
        if args.limit is not None and valid_count >= int(args.limit):
            break

        try:
            obj = json.loads(line)
        except Exception as e:
            summary["skipped_lines"].append(
                {
                    "line": lineno,
                    "error": "bad_json",
                    "details": {"type": type(e).__name__, "message": str(e)},
                    "raw": line[:1000],
                }
            )
            continue

        index = str(obj.get("index") or "").strip()
        repo_path = str(obj.get("repo_path") or "").strip()
        source_file = obj.get("source")
        sink_file = obj.get("sink")

        # 异常数据行：跳过并记录
        missing_keys: List[str] = []
        if not index:
            missing_keys.append("index")
        if not repo_path:
            missing_keys.append("repo_path")
        if not isinstance(source_file, str) or not source_file.strip():
            missing_keys.append("source")
        if not isinstance(sink_file, str) or not sink_file.strip():
            missing_keys.append("sink")

        if missing_keys:
            summary["skipped_lines"].append(
                {
                    "line": lineno,
                    "error": "missing_fields",
                    "details": {"missing": missing_keys},
                    "raw": obj,
                }
            )
            continue

        valid_count += 1

        # 解析目标仓库与规则文件路径（支持相对路径、绝对路径与服务器路径重定位）
        repo_path = _resolve_repo_path(root_path, benchmark_root, repo_path)
        source_file_p = _resolve_against_root(root_path, str(source_file))
        sink_file_p = _resolve_against_root(root_path, str(sink_file))

        # 每个 CVE 跑两遍
        run_specs: List[RunSpec] = [
            RunSpec(index=index, repo_root=repo_path, mode="single", attempt=1, source_file=str(source_file_p), sink_file=str(sink_file_p)),
            RunSpec(index=index, repo_root=repo_path, mode="single", attempt=2, source_file=str(source_file_p), sink_file=str(sink_file_p)),
        #     RunSpec(index=index, repo_root=repo_path, mode="single", attempt=3, source_file=str(source_file_p), sink_file=str(sink_file_p)),
        #     RunSpec(index=index, repo_root=repo_path, mode="single", attempt=4, source_file=str(source_file_p), sink_file=str(sink_file_p)),
        #     RunSpec(index=index, repo_root=repo_path, mode="single", attempt=5, source_file=str(source_file_p), sink_file=str(sink_file_p)),
        ]
        
        all_run_specs.extend(run_specs)
        print(f"[batch] {index} => 2 runs (repo_root={repo_path})")

    print(f"[batch] 总共 {len(all_run_specs)} 个任务，并发度 {args.concurrency}")

    # 使用线程池并发执行
    concurrency = max(1, int(args.concurrency))
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        # 提交所有任务
        future_to_run = {
            executor.submit(
                _run_with_retries,
                root_path=root_path,
                run=run_spec,
                out_dir=out_dir,
                dotenv=args.dotenv,
                timeout_s=args.timeout_s,
                retries=args.retries,
                retry_backoff_s=args.retry_backoff_s,
                no_llm=no_llm,
                max_rounds=max_rounds,
            ): run_spec
            for run_spec in all_run_specs
        }

        # 收集结果
        completed = 0
        for future in as_completed(future_to_run):
            run_spec = future_to_run[future]
            completed += 1
            try:
                results = future.result()
                summary["runs"].extend(results)
                print(f"[batch] [{completed}/{len(all_run_specs)}] {run_spec.run_id} completed")
            except Exception as e:
                # 如果任务本身抛出异常（不是 _run_once 返回的错误）
                error_result = {
                    "run_id": run_spec.run_id,
                    "index": run_spec.index,
                    "mode": run_spec.mode,
                    "attempt": run_spec.attempt,
                    "repo_root": run_spec.repo_root,
                    "source_file": run_spec.source_file,
                    "sink_file": run_spec.sink_file,
                    "ok": False,
                    "exit_code": None,
                    "error": "executor_exception",
                    "details": {"type": type(e).__name__, "message": str(e)},
                }
                summary["runs"].append(error_result)
                print(f"[batch] [{completed}/{len(all_run_specs)}] {run_spec.run_id} executor exception: {e}")

    # 写 summary（单文件，方便统计）
    try:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[batch] 写 summary 失败: {summary_path} ({e})", file=sys.stderr)
        return 2

    print(f"[batch] done. summary => {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

