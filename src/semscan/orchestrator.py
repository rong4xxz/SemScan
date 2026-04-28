"""
Orchestration: assemble skills, parse I/O, invoke Planner/Worker, run rounds,
and write the report.
Prompt details and low-level LLM call logic do not live here.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from semscan.agents.worker import WorkerAgent
from semscan.config import load_dotenv
from semscan.logging_ import get_logger
from semscan.planner import Planner
from semscan.schemas import (
    AgentFinding,
    LocationSpec,
    finding_to_jsonable,
    load_locations_jsonl,
    load_locations_yaml,
    safe_json_loads,
)
from semscan.skills import PipelineStep, SkillsPipeline, build_registry
from semscan.skills.pipeline import REF_BLOCK

logger = get_logger(__name__)


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# File-reading steps that should also go through worker.summary_step.
_READ_TOOLS = {"repo.read_head", "repo.read_window", "repo.read_range"}


class Orchestrator:
    """
    Orchestrates the analysis flow: parse inputs, build skills and agents,
    run preprocessing in parallel, execute the main synthesis rounds, and write the report.
    State includes repo_root, language, registry, pipeline, worker, and optional planner.
    """

    def __init__(
        self,
        *,
        repo_root: str,
        language: str,
        no_llm: bool = False,
        dotenv: str = ".env",
    ):
        self.repo_root_p = Path(repo_root).resolve()
        self.language = language
        self.no_llm = no_llm

        # Build the registry and pipeline.
        self.registry = build_registry(repo_root=str(self.repo_root_p), language=language)
        self.pipeline = SkillsPipeline(registry=self.registry)

        # Load LLMs if enabled.
        main_llm: Optional[Any] = None
        worker_llm: Optional[Any] = None
        if not no_llm:
            load_dotenv(dotenv)
            try:
                from semscan.llm import LLMClient
                api_key = os.getenv("PLANNER_API_KEY") or os.getenv("OPENAI_API_KEY")
                base_url = os.getenv("PLANNER_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
                model = os.getenv("PLANNER_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
                if api_key:
                    main_llm = LLMClient(api_key=api_key, base_url=base_url, model=model)
                worker_key = os.getenv("WORKER_API_KEY") or api_key
                worker_base = os.getenv("WORKER_BASE_URL") or base_url
                worker_model = os.getenv("WORKER_MODEL") or model
                if worker_key:
                    worker_llm = LLMClient(api_key=worker_key, base_url=worker_base, model=worker_model)
            except Exception as e:
                logger.warning("Failed to initialize LLM; falling back to no-llm behavior: %s", e)

        self.worker = WorkerAgent(
            name="worker-small",
            pipeline=self.pipeline,
            registry=self.registry,
            llm=worker_llm,
            logger=logger,
            language=language,
        )
        self.planner = Planner(llm=main_llm, logger=logger) if main_llm else None

    @staticmethod
    def parse_inputs(source_file: str, sink_file: str) -> tuple[List[LocationSpec], List[LocationSpec]]:
        """Parse source/sink files into source and sink location lists."""
        if source_file.endswith(".jsonl"):
            sources = load_locations_jsonl(_read_text(Path(source_file)))
            sinks = load_locations_jsonl(_read_text(Path(sink_file)))
        elif source_file.endswith(".yaml"):
            sources = load_locations_yaml(_read_text(Path(source_file)))
            sinks = load_locations_yaml(_read_text(Path(sink_file)))
        else:
            raise ValueError("source_file/sink_file must be .jsonl or .yaml")
        return sources, sinks

    @staticmethod
    def _parse_plan_to_steps(plan_obj: Dict[str, Any]) -> List[PipelineStep]:
        """Parse a list of PipelineStep objects from the main-agent plan JSON."""
        raw_steps = plan_obj.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return []
        steps: List[PipelineStep] = []
        for s in raw_steps[:10]:
            if not isinstance(s, dict):
                continue
            sid = s.get("id")
            tool = s.get("tool")
            args = s.get("args")
            if not isinstance(sid, str) or not isinstance(tool, str) or not isinstance(args, dict):
                continue
            steps.append(PipelineStep(id=sid, tool=tool, args=args))
        return steps

    @staticmethod
    def _simplify_repo_map_for_prompt(repo_map_finding: AgentFinding) -> Dict[str, Any]:
        """Build a simplified repo_map, including repo_files, for plan/synthesis prompts."""
        j = finding_to_jsonable(repo_map_finding)
        raw = j.get("raw") or {}
        files: List[str] = []
        pipe_results = raw.get("raw_pipeline_results") or raw.get("pipe_results") or {}
        for v in pipe_results.values():
            if isinstance(v, dict) and "files" in v:
                files = v["files"]
                break
        if not files:
            files = raw.get("files") or []
        return {
            "role": j.get("role"),
            "claim": j.get("claim"),
            "confidence": j.get("confidence"),
            "evidence": j.get("evidence", []),
            "next_queries": j.get("next_queries", []),
            "repo_files": files,
        }

    @staticmethod
    def _simplify_local_finding(f: AgentFinding) -> Dict[str, Any]:
        """Simplify a local finding by dropping raw fields before inserting into prompts."""
        j = finding_to_jsonable(f)
        return {
            "role": j.get("role"),
            "claim": j.get("claim"),
            "confidence": j.get("confidence"),
            "evidence": j.get("evidence", []),
            "next_queries": j.get("next_queries", []),
        }

    async def _run_preprocessing(
        self,
        sources: List[LocationSpec],
        sinks: List[LocationSpec],
    ) -> tuple[AgentFinding, List[AgentFinding]]:
        """Run build_repo_map and analyze_location calls in parallel and return their findings."""
        sem = asyncio.Semaphore(6)

        async def _limited(coro):
            async with sem:
                return await coro

        tasks: List[asyncio.Task] = []
        tasks.append(asyncio.create_task(_limited(self.worker.build_repo_map())))
        for s in sources:
            tasks.append(asyncio.create_task(_limited(self.worker.analyze_location(kind="source", loc=s))))
        for s in sinks:
            tasks.append(asyncio.create_task(_limited(self.worker.analyze_location(kind="sink", loc=s))))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error("Task %s failed: %s", i, r)
                raise r
        repo_map_finding: AgentFinding = results[0]
        local_findings: List[AgentFinding] = list(results[1:])
        return repo_map_finding, local_findings

    async def _run_main_loop(
        self,
        sources: List[LocationSpec],
        sinks: List[LocationSpec],
        repo_map_finding: AgentFinding,
        local_findings: List[AgentFinding],
        max_rounds: int,
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Main synthesis loop: plan -> pipeline.run -> summary_step -> synthesise. Returns a placeholder when planner is unavailable."""
        if self.planner is None:
            synthesis = {
                "reachable": "unknown",
                "summary": "(no-llm) no synthesis reasoning was performed",
                "paths": [],
                "gaps": ["LLM is disabled or PLANNER_API_KEY is not configured"],
                "next_actions": ["Configure .env (PLANNER_API_KEY, etc.) and retry without --no-llm"],
            }
            return synthesis, [synthesis]

        tools_doc = self.registry.get_tools_doc().strip() + "\n\n" + REF_BLOCK
        sources_json = json.dumps([asdict(s) for s in sources], ensure_ascii=False)
        sinks_json = json.dumps([asdict(s) for s in sinks], ensure_ascii=False)
        repo_map_json = json.dumps(self._simplify_repo_map_for_prompt(repo_map_finding), ensure_ascii=False)
        local_findings_json = json.dumps([self._simplify_local_finding(f) for f in local_findings], ensure_ascii=False)

        extra_pipelines: List[Dict[str, Any]] = []
        synthesises: List[Dict[str, Any]] = []
        prev_result_str = ""
        synthesis: Dict[str, Any] = {}

        for round_i in range(max_rounds):
            plan_text = await self.planner.plan(
                tools_doc=tools_doc,
                language=self.language,
                sources_json=sources_json,
                sinks_json=sinks_json,
                repo_map_json=repo_map_json,
                local_findings_json=local_findings_json,
                prev_result=prev_result_str,
            )
            plan_obj = safe_json_loads(plan_text) or {}
            steps = self._parse_plan_to_steps(plan_obj)
            extra_pipeline: Dict[str, Any] = {}
            steps_raw = plan_obj.get("steps") or []
            target_map = {s["id"]: s.get("target", "") for s in steps_raw if isinstance(s, dict) and "id" in s}

            if steps:
                extra_pipeline = self.pipeline.run(steps=steps)
                for k, v in extra_pipeline.items():
                    if isinstance(v, dict):
                        v.setdefault("target", target_map.get(k, ""))

            summary_tasks = []
            for step_id, step_res in extra_pipeline.items():
                if isinstance(step_res, dict) and step_res.get("tool") in _READ_TOOLS:
                    summary_tasks.append(
                        asyncio.create_task(self.worker.summary_step(step_results=step_res, step_id=step_id))
                    )
            summary_results = await asyncio.gather(*summary_tasks, return_exceptions=True)
            for res in summary_results:
                if isinstance(res, Exception):
                    continue
                if isinstance(res, (list, tuple)) and len(res) >= 2:
                    sid, summary_text = res[0], res[1]
                    if sid in extra_pipeline and isinstance(extra_pipeline[sid], dict):
                        extra_pipeline[sid]["summary"] = summary_text

            extra_pipelines.append(extra_pipeline)
            extra_evidence_parts = [
                f"round{k} additional evidence collection: {json.dumps(extra_pipelines[k], ensure_ascii=False)}"
                for k in range(round_i + 1)
            ]
            extra_evidence_json = "\n".join(extra_evidence_parts)

            text = await self.planner.synthesise(
                language=self.language,
                sources_json=sources_json,
                sinks_json=sinks_json,
                repo_map_json=repo_map_json,
                local_findings_json=local_findings_json,
                extra_evidence_json=extra_evidence_json,
            )
            synthesis = safe_json_loads(text) or {
                "reachable": "unknown",
                "summary": "The main-agent output could not be parsed as JSON",
                "paths": [],
                "gaps": ["Model output was not valid JSON or did not match the expected format"],
                "next_actions": [],
            }
            synthesis.setdefault("raw_extra_evidence", extra_pipeline)
            synthesis.setdefault("raw_plan_text", plan_text)
            synthesises.append(synthesis)
            prev_result_str = json.dumps(synthesis, ensure_ascii=False)

        return synthesis, synthesises

    def _build_report(
        self,
        sources: List[LocationSpec],
        sinks: List[LocationSpec],
        repo_map_finding: AgentFinding,
        local_findings: List[AgentFinding],
        synthesis: Dict[str, Any],
        synthesises: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assemble the report dictionary. ``synthesis`` is the final round, and ``prev_synthesis`` contains earlier rounds, matching semscan behavior."""
        # Token accounting is split between planner and worker for batch-summary aggregation.
        planner_usage = (
            self.planner.llm.usage.to_dict() if self.planner is not None else None
        )
        worker_usage = (
            self.worker.llm.usage.to_dict() if self.worker.llm is not None else None
        )
        return {
            "meta": {
                "repo_root": str(self.repo_root_p),
                "language": self.language,
                "no_llm": self.no_llm,
                "token_usage": {
                    "planner": planner_usage,
                    "worker": worker_usage,
                },
            },
            "inputs": {
                "sources": [asdict(s) for s in sources],
                "sinks": [asdict(s) for s in sinks],
            },
            "repo_map": finding_to_jsonable(repo_map_finding),
            "local_findings": [finding_to_jsonable(f) for f in local_findings],
            "synthesis": synthesis,
            "prev_synthesis": synthesises[:-1] if len(synthesises) > 1 else [],
        }

    async def run(
        self,
        *,
        source_file: str,
        sink_file: str,
        out_file: str,
        max_rounds: int = 3,
    ) -> Dict[str, Any]:
        """
        Execute the full orchestration flow: parse inputs -> parallel preprocessing ->
        main synthesis rounds -> write report.
        """
        sources, sinks = self.parse_inputs(source_file, sink_file)
        repo_map_finding, local_findings = await self._run_preprocessing(sources, sinks)
        synthesis, synthesises = await self._run_main_loop(
            sources, sinks, repo_map_finding, local_findings, max_rounds
        )
        report = self._build_report(
            sources, sinks, repo_map_finding, local_findings, synthesis, synthesises
        )
        Path(out_file).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Report written to %s", out_file)
        return report


async def run_analysis(
    *,
    repo_root: str,
    language: str,
    source_file: str,
    sink_file: str,
    out_file: str,
    no_llm: bool = False,
    dotenv: str = ".env",
    max_rounds: int = 5,
) -> Dict[str, Any]:
    """
    Orchestration entrypoint: create an Orchestrator and execute run().
    Aligned with semscan behavior and intended for direct use from main or scripts.
    """
    orch = Orchestrator(
        repo_root=repo_root,
        language=language,
        no_llm=no_llm,
        dotenv=dotenv,
    )
    return await orch.run(
        source_file=source_file,
        sink_file=sink_file,
        out_file=out_file,
        max_rounds=max_rounds,
    )
