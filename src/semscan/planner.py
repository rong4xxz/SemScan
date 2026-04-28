"""
The main agent's planning and synthesis logic: produces the main plan text and
the synthesis text.
Prompts live in this file.
It does not parse JSON, execute pipelines, or write files.
"""
from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from typing import Any, Optional

from semscan.llm import ChatMessage, LLMClient
from semscan.logging_ import get_logger
from semscan.skills.pipeline import REF_BLOCK

logger = get_logger(__name__)


@dataclass(frozen=True)
class PromptPack:
    system: str
    user: str

def _build_plan_prompt(
    *,
    tools_doc: str,
    language: str,
    sources_json: str,
    sinks_json: str,
    repo_map_json: str,
    local_findings_json: str,
    prev_result: str = "",
) -> PromptPack:
    """Main planning prompt: ask the LLM for JSON containing steps. tools_doc comes from registry.get_tools_doc() plus REF_BLOCK."""
    system = (
        "You are a planner (global coordinator). "
        "Your ultimate goal is to find paths from source to sink. "
        "To do that, first output a pipeline plan for additional evidence collection "
        "(searching / opening key files). "
        "Output must be a strict JSON object, not Markdown."
    )
    user = textwrap.dedent(f"""
        Language: {language}

        Source list (JSON):
        {sources_json}

        Sink list (JSON):
        {sinks_json}

        Repo map (JSON):
        {repo_map_json}

        Worker-agent local analysis results (JSON array):
        {local_findings_json}

        Results from the previous round of main-agent source-to-sink synthesis (JSON array):
        {prev_result}

        {tools_doc}

        {REF_BLOCK}

        Output JSON in this shape:
        {{
          "role": "pipeline_plan",
          "steps": [
            {{"id": "s0", "tool": "repo.search_text", "args": {{"needle": "TODO", "max_hits": 5, "case_sensitive": false}}, "target": "Describe the goal of this step"}}
          ]
        }}

        Planning guidance:
        - Analyze the worker agents' local findings and the previous synthesis result to identify unresolved questions and knowledge gaps.
        - Build a supplemental investigation plan based on earlier findings, and avoid repeating evidence-collection steps that have already run.
        - Prioritize "gaps" (missing information) and "next_actions" (recommended follow-up actions) mentioned in earlier analysis.
        - If earlier rounds already found a concrete path, plan how to verify or extend it.
        - If earlier analysis was inconclusive, plan a deeper investigation.

        Constraints:
        - At most 8 steps, and keep max_hits <= 20.
        - Do not repeat the same evidence-collection steps from earlier rounds.
        - Output JSON only.
    """).strip()
    return PromptPack(system=system, user=user)


def _build_synthesis_prompt(
    *,
    language: str,
    sources_json: str,
    sinks_json: str,
    repo_map_json: str,
    local_findings_json: str,
    extra_evidence_json: str,
) -> PromptPack:
    """Main synthesis prompt: ask the LLM to produce a conclusion JSON object."""
    system = (
        "You are a professional data-flow analyst who can untangle complex code paths. "
        "You may use static.* results for orientation, but final evidence must come from code text read by repo.read_* plus worker-agent and supplemental evidence results. "
        "Enumerate as many possible source-to-sink data-flow paths as you can, even if later you conclude some paths are uncertain. "
        "Output must be a strict JSON object."
    )
    user = textwrap.dedent(f"""
        Language: {language}

        Source list (JSON):
        {sources_json}

        Sink list (JSON):
        {sinks_json}

        Repo map (JSON):
        {repo_map_json}

        Worker-agent local analysis results (JSON array):
        {local_findings_json}

        Supplemental evidence collected across all rounds:
        {extra_evidence_json}

        Output JSON in this shape:
        {{
          "reachable": "yes|no|unknown",
          "summary": "One-sentence summary of all discovered data-flow paths",
          "paths": [
            [
              {{
                "step": 1,
                "claim": "How this hop propagates data from the source to the next location",
                "evidence": [{{"path":"","start_line":0,"end_line":0,"excerpt":"Must be copied verbatim from code text returned by repo.read_* (source code with line numbers)"}}]
              }}
            ]
          ],
          "gaps": ["Why the result cannot yet be proven or disproven (what evidence is missing)"],
          "next_actions": ["Parallelizable next tasks (for semscan which symbol to search or which file to open)"]
        }}

        Analysis guidance:
        - Source and sink entries may contain unusual symbol names, such as Attribute or Fstring. Focus primarily on whether the data actually flows into the sink location identified by path and line.
        - When you see class instantiation, remember that Python has many implicit assignment semantics. For semscan, classes inheriting from BaseModel may not define __init__ explicitly, but constructor arguments are still assigned to attributes automatically.
        - Also watch for implicit calls such as Pydantic constructors and validators triggered by decorators like @field_validator.

        Constraints:
        - paths must be an array containing all discovered data-flow paths, and each path is an array of steps.
        - reachable may be "yes" only if at least one complete path is found.
        - Every step in every path must be supported by evidence.
        - Whenever data flows across functions, explicitly explain the evidence for that cross-function hop.
        - If no path is found, set paths to an empty array and reachable to "no" or "unknown".
        - Do not invent evidence; if none exists, say unknown and use gaps/next_actions.
        - gaps must not include items that could already be solved by the supplemental evidence provided.
        - next_actions may contain at most 10 actionable follow-up tasks.
        - Output JSON only, with no extra explanation.
    """).strip()
    return PromptPack(system=system, user=user)


class Planner:
    """Main agent: two LLM calls, one for planning and one for synthesis."""

    def __init__(self, *, llm: LLMClient, logger: Optional[logging.Logger] = None):
        self.llm = llm
        self._log = logger if logger is not None else get_logger(__name__)

    async def plan(
        self,
        *,
        tools_doc: str,
        language: str,
        sources_json: str,
        sinks_json: str,
        repo_map_json: str,
        local_findings_json: str,
        prev_result: str = "",
    ) -> str:
        """
        Return the raw main-plan text (a JSON string containing steps).
        tools_doc is fetched by the caller from registry.get_tools_doc().
        """
        pack = _build_plan_prompt(
            tools_doc=tools_doc,
            language=language,
            sources_json=sources_json,
            sinks_json=sinks_json,
            repo_map_json=repo_map_json,
            local_findings_json=local_findings_json,
            prev_result=prev_result,
        )
        self._log.debug(
            "plan start: language=%s, repo_map_len=%d, local_findings_len=%d, prev_result_len=%d",
            language, len(repo_map_json), len(local_findings_json), len(prev_result),
        )
        self._log.info("plan request: user length=%d", len(pack.user))
        messages = [
            ChatMessage(role="system", content=pack.system),
            ChatMessage(role="user", content=pack.user),
        ]
        plan_text = await self.llm.chat(messages=messages, temperature=0.1)
        self._log.info("plan response: text length=%d", len(plan_text))
        self._log.debug("plan response prefix: %s", (plan_text[:400] + "…") if len(plan_text) > 400 else plan_text)
        return plan_text

    async def synthesise(
        self,
        *,
        language: str,
        sources_json: str,
        sinks_json: str,
        repo_map_json: str,
        local_findings_json: str,
        extra_evidence_json: str,
    ) -> str:
        """Return the raw synthesis text (a JSON string)."""
        pack = _build_synthesis_prompt(
            language=language,
            sources_json=sources_json,
            sinks_json=sinks_json,
            repo_map_json=repo_map_json,
            local_findings_json=local_findings_json,
            extra_evidence_json=extra_evidence_json,
        )
        self._log.debug(
            "synthesis start: language=%s, extra_evidence_len=%d",
            language, len(extra_evidence_json),
        )
        self._log.info("synthesis request: user length=%d", len(pack.user))
        messages = [
            ChatMessage(role="system", content=pack.system),
            ChatMessage(role="user", content=pack.user),
        ]
        text = await self.llm.chat(messages=messages, temperature=0.2)
        self._log.info("synthesis response: text length=%d", len(text))
        self._log.debug("synthesis response prefix: %s", (text[:400] + "…") if len(text) > 400 else text)
        return text
