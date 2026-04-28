"""
Worker agent responsibilities: repo_map, single-location analyze_location,
and step summaries. Uses an injected Pipeline internally.
Prompts live in this file and are adapted from semscan.
"""
from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from semscan.llm import ChatMessage, LLMClient
from semscan.logging_ import get_logger
from semscan.schemas import AgentFinding, Evidence, LocationSpec, QuerySpec, safe_json_loads
from semscan.skills import PipelineStep, SkillsPipeline
from semscan.skills.pipeline import REF_BLOCK
from semscan.skills.registry import ToolRegistry

logger = get_logger(__name__)


@dataclass(frozen=True)
class PromptPack:
    system: str
    user: str


def _get_tools_doc_for_worker(registry: Optional[ToolRegistry]) -> str:
    """Tool documentation for worker planning: prefer registry.get_tools_doc() and append REF_BLOCK; if no registry is provided, return REF_BLOCK only."""
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
    """Worker phase 1: produce a pipeline plan with one-shot multi-step tool calls."""
    system = (
        "You are a code-audit and data-flow analysis assistant. "
        "First output an executable pipeline plan (JSON) so the system can read/search code. "
        "You may use static.* tools for locating ranges, but final evidence must come from code text returned by repo.read_*. "
        "Output must be a strict JSON object, not Markdown."
    )
    sym = symbol or ""
    user = textwrap.dedent(f"""
        Task: generate an evidence-collection pipeline plan for a {kind} location in a {language} project.

        Location:
        - path: {rel_path}
        - line: {line}
        - symbol: {sym}

        {tools_doc}

        Output JSON using this schema (all fields are required):
        {{
          "role": "pipeline_plan",
          "steps": [
            {{"id": "w0", "tool": "repo.read_window", "args": {{"rel_path": "{rel_path}", "line": {line}, "window": 80}}}}
          ]
        }}

        Constraints:
        - You may use any tool listed above; do not limit yourself to the semscan tool in the schema.
        - Use at most 6 steps, and prefer including repo.read_window (w0) for the target location.
        - If the exact location is unclear, you may first use gnu.rg / repo.search_text to find it, then call repo.read_window.
        - Keep max_hits <= 20 for gnu.rg / repo.search_text.
        - Output JSON only, with no extra explanation.
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
    """Worker phase 2: produce a structured finding from pipeline execution results."""
    system = (
        "You are a code-audit and data-flow analysis assistant. "
        "The system has already executed your earlier pipeline plan and is giving you the real outputs. "
        "You must reason only from those outputs and must not fabricate evidence. "
        "Output must be a strict JSON object, not Markdown."
    )
    sym = symbol or ""
    user = textwrap.dedent(f"""
        Task: based on tool outputs, analyze how data is created, propagated, and used around this {kind} location.

        Location:
        - path: {rel_path}
        - line: {line}
        - symbol: {sym}

        Pipeline execution results (JSON):
        {pipeline_results_json}

        Output JSON using this schema (all fields are required):
        {{
          "role": "local_context",
          "claim": "One-sentence summary of what happens near this location, specifically from a data-flow perspective",
          "confidence": 0.0,
          "evidence": [
            {{
              "path": "{rel_path}",
              "start_line": 0,
              "end_line": 0,
              "excerpt": "Must be copied verbatim from text/excerpt in the pipeline result (source code with line numbers)"
            }}
          ],
          "next_queries": [
            {{
              "type": "ref_query",
              "symbol": "Symbol name to query next",
              "file": "Optional file path",
              "line_number": 123
            }}
          ]
        }}

        Constraints:
        - evidence.excerpt must come directly from the pipeline result; do not rewrite it.
        - start_line/end_line should match the excerpt; if the excerpt comes from read_window, approximate using its start_line/end_line.
        - confidence must be in the range 0~1.
        - next_queries should contain structured query objects (at most 8), each with type ("ref_query" or "def_query"), symbol (required), file (optional), and line_number (optional) for follow-up path tracing.
    """).strip()
    return PromptPack(system=system, user=user)


def _build_repo_map_synthesis_prompt(
    *,
    language: str,
    pipeline_results_json: str,
) -> PromptPack:
    """Summarize repo_map from repo-tool output."""
    system = (
        "You are a fast codebase scanning assistant. "
        "The system has already executed the pipeline plan and is giving you the real outputs. "
        "Infer only from those outputs; do not invent files that do not exist. "
        "Output must be a strict JSON object."
    )
    user = textwrap.dedent(f"""
        Goal: provide a module map for the {language} project plus likely data entry/exit locations, based only on filenames and common conventions. Uncertainty is allowed.

        Pipeline execution results (JSON):
        {pipeline_results_json}

        Output JSON schema:
        {{
          "role": "repo_map",
          "claim": "One-sentence summary of the repository structure",
          "confidence": 0.0,
          "evidence": [
            {{
              "path": "(virtual)",
              "start_line": 0,
              "end_line": 0,
              "excerpt": "Copy several representative paths from the files field in the pipeline result"
            }}
          ]
        }}

        Constraints:
        - start_line/end_line should match the excerpt; if you are unsure, use 0 for both.
        - confidence must be in the range 0~1.
        - Output JSON only, with no explanatory text.
    """).strip()
    return PromptPack(system=system, user=user)


def _build_worker_summary_step_prompt(
    *,
    language: str,
    step_result_json: str,
) -> PromptPack:
    """Summarize a single pipeline-step result."""
    system = (
        "You are a code-audit and data-flow analysis assistant. "
        "The system has executed one step from the plan and is giving you that step's result as JSON. "
        "You must reason only from this output and must not fabricate evidence. "
        "Output must be a strict string value, not Markdown."
    )
    user = textwrap.dedent(f"""
        Task: based on the single-step execution result below (step_result_json) and the step's `target` field,
        produce a local data-flow summary using only the provided textual evidence.

        step_result_json:
        {step_result_json}

        Output a string only.
        Constraints:
        - Use only the contents of step_result_json as evidence.
        - Output the summary text only, with no extra wording.
    """).strip()
    return PromptPack(system=system, user=user)


def _plan_to_steps(obj: Dict[str, Any]) -> Optional[List[PipelineStep]]:
    """Parse a PipelineStep list from LLM plan JSON."""
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
    """Convert LLM output JSON into an AgentFinding."""
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
    """Worker agent: performs local reading/search tasks and returns structured JSON."""

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
            pipeline: SkillsPipeline injected externally and shared with the main flow
            registry: Tool registry shared with pipeline; used to build plan prompts via get_tools_doc(). If omitted, planning only receives $ref documentation.
            llm: Worker LLM for planning/synthesis; if None, only runs the pipeline without semantic summarization
            logger: Optional logger
            language: Project language used in prompts
        """
        self.name = name
        self.pipeline = pipeline
        self._registry = registry
        self.llm = llm
        self._log = logger if logger is not None else get_logger(__name__)
        self.language = language

    async def build_repo_map(self) -> AgentFinding:
        """Build repo_map by running repo.repo_tree internally and then summarizing it with the LLM."""
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
        """Perform local analysis for one source/sink location: plan -> pipeline.run -> synthesis."""
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

        # 1) plan (tool documentation comes from registry.get_tools_doc() + REF_BLOCK)
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

        # 2) synthesis
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
        """Summarize one pipeline-step result and return (step_id, summary_text)."""
        if self.llm is None:
            ev = Evidence(path="(virtual)", start_line=0, end_line=0, excerpt=json.dumps(step_results)[:1000])
            finding_dict = {
                "role": "step_summary",
                "claim": "(no-llm) no summary was generated",
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
    """Build a minimal repo_map finding from pipeline results when no LLM is available."""
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
        claim="(no-llm) returned only the file list; no natural-language map was generated",
        confidence=0.2,
        evidence=[ev],
        next_queries=[
            QuerySpec(type="ref_query", symbol="Open entry files"),
            QuerySpec(type="ref_query", symbol="Search for source/sink-related symbols"),
        ],
        raw={"pipe_results": pipe_results},
    )


def _location_no_llm_finding(
    *,
    kind: str,
    loc: LocationSpec,
    pipe_results: Dict[str, Any],
) -> AgentFinding:
    """Build a minimal local_context finding from pipeline results when no LLM is available."""
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
        claim=f"(no-llm) local context for the {kind} location was read, but no semantic analysis was performed",
        confidence=0.2,
        evidence=[ev],
        next_queries=[QuerySpec(type="ref_query", symbol=loc.symbol)] if loc.symbol else [],
        raw={"kind": kind, "path": loc.path, "line": loc.line},
    )
