"""
Worker Agent: repo_map, single point analyze_location, step summary.
Prompts are written in this file
"""
from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from example.llm import ChatMessage, LLMClient
from example.logging_ import get_logger
from example.schemas import AgentFinding, Evidence, LocationSpec, QuerySpec, safe_json_loads
from example.skills import PipelineStep, SkillsPipeline
from example.skills.pipeline import REF_BLOCK
from example.skills.registry import ToolRegistry

logger = get_logger(__name__)


@dataclass(frozen=True)
class PromptPack:
    system: str
    user: str


def _get_tools_doc_for_worker(registry: Optional[ToolRegistry]) -> str:
    tools_list = registry.get_tools_doc() if registry else ""
    if not tools_list:
        return REF_BLOCK
    return tools_list.strip() + "\n\n" + REF_BLOCK


def _build_local_context_plan_prompt(
    *,
    kind: str,
    rel_path: str,
    line: int,
    symbol: Optional[str],
    language: str,
    tools_doc: str,
) -> PromptPack:
    """First step of the Worker Agent: generate a pipeline plan for a single point."""
    system = (
        "You are a code analysis/data flow analysis assistant."
        "You need to output a executable pipeline plan (JSON) first, and let the system read/search the code."
        "You can use static.* tools to locate the range, but the final evidence must come from the code content read by repo.read_*."
        "The output must be a strict JSON object (not Markdown)."
    )
    sym = symbol or ""
    user = textwrap.dedent(f"""
        Task: Generate a "proof pipeline plan" (pipeline plan) for a {kind} point in the {language} project, for subsequent data flow analysis.

        Point:
        - path: {rel_path}
        - line: {line}
        - symbol: {sym}

        {tools_doc}

        Please output JSON, the schema is as follows (all fields must exist):
        {{
          "role": "pipeline_plan",
          "steps": [
            {{"id": "w0", "tool": "repo.read_window", "args": {{"rel_path": "{rel_path}", "line": {line}, "window": 80}}}}
          ]
        }}

        Constraints (very important):
        - You can use any tool listed in the above document, not limited by the example tools in the schema
        - The maximum number of steps is 6, and the repo.read_window (w0) should be included first
        - When the point location is unknown, you can first do gnu.rg / repo.search_text to query the specific location of the point, and then call repo.read_window
        - The max_hits of gnu.rg / repo.search_text should be controlled <= 20
        - The output must be a strict JSON object (not Markdown).
    """).strip()
    return PromptPack(system=system, user=user)


def _build_local_context_synthesis_prompt(
    *,
    kind: str,
    rel_path: str,
    line: int,
    symbol: Optional[str],
    pipeline_results_json: str,
) -> PromptPack:
    """Second step of the Worker Agent: generate a structured finding based on the pipeline execution results."""
    system = (
        "You are a code analysis/data flow analysis assistant."
        "The system has executed the pipeline plan you output, and provided the real output to you."
        "You must only make judgments based on these outputs, and do not fabricate evidence."
        "The output must be a strict JSON object (not Markdown)."
    )
    sym = symbol or ""
    user = textwrap.dedent(f"""
        Task: Analyze a {kind} point in the local context of "how data is produced/passed/used" based on the tool outputs.

        Point:
        - path: {rel_path}
        - line: {line}
        - symbol: {sym}

        Pipeline execution results (JSON):
        {pipeline_results_json}

        Please output JSON, the schema is as follows (all fields must exist):
        {{
          "role": "local_context",
          "claim": "A summary of what happened near this point (related to data flow)",
          "confidence": 0.0,
          "evidence": [
            {{
              "path": "{rel_path}",
              "start_line": 0,
              "end_line": 0,
              "excerpt": "Must be copied exactly from the text/excerpt in the pipeline results (source code with line numbers)"
            }}
          ],
          "next_queries": [
            {{
              "type": "ref_query",
              "symbol": "The symbol to query",
              "file": "Optional file path",
              "line_number": 123
            }}
          ]
        }}

        Constraints:
        - evidence.excerpt must come from the pipeline results (do not rewrite)
        - start_line/end_line must correspond to the excerpt (if the excerpt comes from read_window, use its start_line/end_line to roughly annotate)
        - confidence range is 0~1
        - next_queries should contain structured query objects (up to 8), each object contains type (value is "ref_query" or "def_query"), symbol (required), file (optional) and line_number (optional), for subsequent tracing of data flow paths
    """).strip()
    return PromptPack(system=system, user=user)


def _build_repo_map_synthesis_prompt(
    *,
    language: str,
    pipeline_results_json: str,
) -> PromptPack:
    """Based on the repo tool outputs, let the LLM summarize the repo_map."""
    system = (
        "You are a code repository quick scan assistant."
        "The system has executed the pipeline plan, and provided the real output to you."
        "You can only make inferences based on these outputs, do not fabricate non-existent files."
        "The output must be a strict JSON object."
    )
    user = textwrap.dedent(f"""
        Task: Give the "module map" and potential data entry/exit locations of the {language} project (based on file names and common conventions, allow uncertainty).

        Pipeline execution results (JSON):
        {pipeline_results_json}

        Output JSON schema:
        {{
          "role": "repo_map",
          "claim": "A summary of the repository's rough structure",
          "confidence": 0.0,
          "evidence": [
            {{
              "path": "(virtual)",
              "start_line": 0,
              "end_line": 0,
              "excerpt": "Copy a few representative paths from the files in the pipeline results"
            }}
          ]
        }}

        Constraints:
        - start_line/end_line must correspond to the excerpt (if you are not sure how to fill it, fill in 0 for both)
        - confidence range is 0~1
        - The output must be a strict JSON object (not Markdown).
    """).strip()
    return PromptPack(system=system, user=user)


def _build_worker_summary_step_prompt(
    *,
    language: str,
    step_result_json: str,
) -> PromptPack:
    """Summarize the result of a single pipeline step."""
    system = (
        "You are a code analysis/data flow analysis assistant."
        "The system has executed a step in the plan, and provided the execution results (JSON) to you."
        "You must only make judgments based on these outputs, do not fabricate evidence."
        "The output must be a strict string object (not Markdown)."
    )
    user = textwrap.dedent(f"""
        Task: Generate a local data flow summary (based on the provided text evidence) based on the single step execution results (step_result_json) and the `target` field of that step.

        Single step execution results (JSON):
        {step_result_json}

        Please output a strict string object.
        Constraints:
        - Only use the content in step_result_json as evidence.
        - Must only output the summary itself, no additional text.
    """).strip()
    return PromptPack(system=system, user=user)


def _plan_to_steps(obj: Dict[str, Any]) -> Optional[List[PipelineStep]]:
    """Parse the PipelineStep list from the LLM plan JSON."""
    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return None
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
    return steps or None


def _to_finding(obj: Dict[str, Any], *, fallback_role: str, fallback_raw: Dict[str, Any]) -> AgentFinding:
    """Convert the JSON output by the LLM to AgentFinding."""
    role = str(obj.get("role") or fallback_role)
    claim = str(obj.get("claim") or "")
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    evidences: List[Evidence] = []
    for e in obj.get("evidence") or []:
        if not isinstance(e, dict):
            continue
        try:
            evidences.append(
                Evidence(
                    path=str(e.get("path") or ""),
                    start_line=int(e.get("start_line") or 0),
                    end_line=int(e.get("end_line") or 0),
                    excerpt=str(e.get("excerpt") or ""),
                )
            )
        except Exception:
            continue

    next_queries_raw = obj.get("next_queries") or []
    next_queries: List[QuerySpec] = []
    if isinstance(next_queries_raw, list):
        for item in next_queries_raw[:8]:
            if isinstance(item, dict):
                try:
                    next_queries.append(QuerySpec.from_dict(item))
                except (ValueError, KeyError, TypeError):
                    continue
            elif isinstance(item, str) and item.strip():
                next_queries.append(QuerySpec(type="ref_query", symbol=item.strip()))

    raw = obj if obj else fallback_raw
    return AgentFinding(role=role, claim=claim, confidence=confidence, evidence=evidences, next_queries=next_queries, raw=raw)


class WorkerAgent:
    """Worker Agent: do local reading/searching tasks, return structured JSON."""

    def __init__(
        self,
        *,
        name: str,
        pipeline: SkillsPipeline,
        registry: Optional[ToolRegistry] = None,
        llm: Optional[LLMClient] = None,
        logger: Optional[logging.Logger] = None,
        language: str = "python",
    ):
        """
        Args:
            name: Agent name
            pipeline: SkillsPipeline injected from the outside (shared with the main process)
            registry: Tool registry shared with the pipeline, used to generate plan prompts with get_tools_doc(); if not passed, the plan only contains $ref instructions
            llm: Sub-LLM, used for plan/synthesis; if None, only run the pipeline without semantic summary
            logger: Optional, for logging
            language: Project language, used for prompt
        """
        self.name = name
        self.pipeline = pipeline
        self._registry = registry
        self.llm = llm
        self._log = logger if logger is not None else get_logger(__name__)
        self.language = language

    async def build_repo_map(self) -> AgentFinding:
        """Build repo_map: run pipeline internally (repo.repo_tree), then let the LLM summarize."""
        steps = [PipelineStep(id="t0", tool="repo.repo_tree", args={"max_entries": 400})]
        pipe_results = self.pipeline.run(steps=steps)

        if self.llm is None:
            return _repo_map_no_llm_finding(pipe_results)

        self._log.debug("build_repo_map: pipeline_results keys=%s", list(pipe_results.keys()))
        pack = _build_repo_map_synthesis_prompt(
            language=self.language,
            pipeline_results_json=json.dumps(pipe_results, ensure_ascii=False),
        )
        messages = [
            ChatMessage(role="system", content=pack.system),
            ChatMessage(role="user", content=pack.user),
        ]
        self._log.info("build_repo_map: synthesis request user length=%d", len(pack.user))
        text = await self.llm.chat(messages=messages, temperature=0.2)
        self._log.info("build_repo_map: synthesis response length=%d", len(text))
        obj = safe_json_loads(text) or {}
        obj.setdefault("raw_plan_text", "")
        obj.setdefault("raw_pipeline_results", pipe_results)
        obj.setdefault("raw_model_text", text)
        return _to_finding(
            obj,
            fallback_role="repo_map",
            fallback_raw={"raw_plan_text": "", "raw_pipeline_results": pipe_results, "raw_model_text": text},
        )

    async def analyze_location(self, *, kind: str, loc: LocationSpec) -> AgentFinding:
        """Analyze a single source/sink point: plan → pipeline.run → synthesis."""
        fallback_steps = [
            PipelineStep(id="s0", tool="static.locate_method_by_line", args={"rel_path": loc.path, "line": loc.line}),
            PipelineStep(
                id="r0",
                tool="repo.read_range",
                args={
                    "rel_path": {"$ref": "s0.path"},
                    "start_line": {"$ref": "s0.start_line"},
                    "end_line": {"$ref": "s0.end_line"},
                },
            ),
            PipelineStep(id="w0", tool="repo.read_window", args={"rel_path": loc.path, "line": loc.line, "window": 80}),
        ]

        if self.llm is None:
            pipe_results = self.pipeline.run(steps=fallback_steps)
            return _location_no_llm_finding(kind=kind, loc=loc, pipe_results=pipe_results)

        # 1) plan (tool descriptions from registry.get_tools_doc() + REF_BLOCK)
        tools_doc = _get_tools_doc_for_worker(self._registry)
        plan_pack = _build_local_context_plan_prompt(
            kind=kind,
            rel_path=loc.path,
            line=loc.line,
            symbol=loc.symbol,
            language=self.language,
            tools_doc=tools_doc,
        )
        self._log.debug("analyze_location: kind=%s path=%s line=%s", kind, loc.path, loc.line)
        self._log.info("analyze_location: plan request user length=%d", len(plan_pack.user))
        plan_text = await self.llm.chat(
            messages=[
                ChatMessage(role="system", content=plan_pack.system),
                ChatMessage(role="user", content=plan_pack.user),
            ],
            temperature=0.1,
        )
        self._log.info("analyze_location: plan response length=%d", len(plan_text))
        plan_obj = safe_json_loads(plan_text) or {}
        steps = _plan_to_steps(plan_obj) or fallback_steps
        pipe_results = self.pipeline.run(steps=steps)

        # 2) synthesis (generate a structured finding based on the pipeline execution results)
        synth_pack = _build_local_context_synthesis_prompt(
            kind=kind,
            rel_path=loc.path,
            line=loc.line,
            symbol=loc.symbol,
            pipeline_results_json=json.dumps(pipe_results, ensure_ascii=False),
        )
        self._log.info("analyze_location: synthesis request user length=%d", len(synth_pack.user))
        text = await self.llm.chat(
            messages=[
                ChatMessage(role="system", content=synth_pack.system),
                ChatMessage(role="user", content=synth_pack.user),
            ],
            temperature=0.2,
        )
        self._log.info("analyze_location: synthesis response length=%d", len(text))
        obj = safe_json_loads(text) or {}
        obj.setdefault("raw_plan_text", plan_text)
        obj.setdefault("raw_pipeline_results", pipe_results)
        obj.setdefault("raw_model_text", text)
        obj.setdefault("kind", kind)
        return _to_finding(
            obj,
            fallback_role="local_context",
            fallback_raw={"raw_plan_text": plan_text, "raw_pipeline_results": pipe_results, "raw_model_text": text, "kind": kind},
        )

    async def summary_step(self, *, step_results: Dict[str, Any], step_id: str) -> Tuple[str, str]:
        """Summarize the result of a single pipeline step, return (step_id, summary_text)."""
        if self.llm is None:
            ev = Evidence(path="(virtual)", start_line=0, end_line=0, excerpt=json.dumps(step_results)[:1000])
            finding_dict = {
                "role": "step_summary",
                "claim": "(no-llm) No summary generated",
                "confidence": 0.2,
                "evidence": [{"path": ev.path, "start_line": ev.start_line, "end_line": ev.end_line, "excerpt": ev.excerpt}],
                "next_queries": [],
                "raw": {"step_results": step_results},
            }
            return step_id, json.dumps(finding_dict, ensure_ascii=False)

        pack = _build_worker_summary_step_prompt(
            language=self.language,
            step_result_json=json.dumps(step_results, ensure_ascii=False),
        )
        messages = [
            ChatMessage(role="system", content=pack.system),
            ChatMessage(role="user", content=pack.user),
        ]
        text = await self.llm.chat(messages=messages, temperature=0.2)
        return step_id, text.strip()


def _repo_map_no_llm_finding(pipe_results: Dict[str, Any]) -> AgentFinding:
    """Construct the minimum repo_map finding when there is no LLM."""
    t0 = pipe_results.get("t0")
    if isinstance(t0, list):
        excerpt = "\n".join(str(x) for x in t0[:10])
    elif isinstance(t0, dict) and "files" in t0:
        excerpt = "\n".join(str(x) for x in (t0["files"] or [])[:10])
    else:
        excerpt = json.dumps(t0)[:1000] if t0 is not None else "{}"
    ev = Evidence(path="(virtual)", start_line=0, end_line=0, excerpt=excerpt)
    return AgentFinding(
        role="repo_map",
        claim="(no-llm) Only return file list, no natural language map generated",
        confidence=0.2,
        evidence=[ev],
        next_queries=[
            QuerySpec(type="ref_query", symbol="Open entry file"),
            QuerySpec(type="ref_query", symbol="Search source/sink related symbols"),
        ],
        raw={"pipe_results": pipe_results},
    )


def _location_no_llm_finding(
    *,
    kind: str,
    loc: LocationSpec,
    pipe_results: Dict[str, Any],
) -> AgentFinding:
    """Construct the minimum local_context finding when there is no LLM."""
    excerpt = ""
    start, end = 0, 0
    for v in pipe_results.values():
        if isinstance(v, dict):
            if "excerpt" in v:
                excerpt = str(v["excerpt"])[:1000]
                start = int(v.get("start_line") or 0)
                end = int(v.get("end_line") or 0)
                break
            if "text" in v:
                excerpt = str(v["text"])[:1000]
                break
        elif isinstance(v, str):
            excerpt = v[:1000]
            break
    if not excerpt:
        excerpt = json.dumps(pipe_results)[:1000]
    ev = Evidence(path=loc.path, start_line=start, end_line=end, excerpt=excerpt)
    return AgentFinding(
        role="local_context",
        claim=f"(no-llm) {kind} point local context has been read, no semantic analysis has been done",
        confidence=0.2,
        evidence=[ev],
        next_queries=[QuerySpec(type="ref_query", symbol=loc.symbol)] if loc.symbol else [],
        raw={"kind": kind, "path": loc.path, "line": loc.line},
    )
