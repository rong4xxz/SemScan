"""
Main Agent's "plan" and "synthesis": produce main plan text, synthesis text.
Prompts written in this file;
Do not parse JSON, do not execute pipeline, do not write file.
"""
from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from typing import Any, Optional

from example.llm import ChatMessage, LLMClient
from example.logging_ import get_logger
from example.skills.pipeline import REF_BLOCK

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
    """Main plan: let LLM produce JSON containing steps. tools_doc from registry.get_tools_doc(), append REF_BLOCK."""
    system = (
        "You are a planner (global scheduler)."
        "Your final goal is to find the source to sink link. To achieve this goal, you need to first output a pipeline plan, to supplement the evidence (search/open key files)."
        "Output must be a strict JSON object (do not use Markdown)."
    )
    user = textwrap.dedent(f"""
        Language: {language}

        source list (JSON):
        {sources_json}

        sink list (JSON):
        {sinks_json}

        repo_map (JSON):
        {repo_map_json}

        Sub Agent local analysis results (JSON array):
        {local_findings_json}

        The result of the main Agent's comprehensive analysis of the source to sink link in the previous round (JSON array):
        {prev_result}

        {tools_doc}

        {REF_BLOCK}

        Please output JSON:
        {{
          "role": "pipeline_plan",
          "steps": [
            {{"id": "s0", "tool": "repo.search_text", "args": {{"needle": "TODO", "max_hits": 5, "case_sensitive": false}}, "target": "describe the purpose of this step"}}
          ]
        }}

        Planning guidance:
        - Analyze the local analysis results of the sub Agent and the comprehensive analysis results of the previous round, identify unresolved problems and knowledge gaps
        - Based on the previous discovery, make a plan to supplement the investigation, avoid repeating the evidence steps that have already been executed
        - Prioritize the "gaps" (missing information) and "next_actions" (suggested actions) mentioned in the previous analysis
        - If the previous analysis has found a clear link, make a plan to verify or expand the link
        - If the previous analysis is inconclusive (uncertain), make a plan to investigate deeper

        Constraints:
        - steps are limited to 8, max_hits is limited to <= 20
        - Do not repeat the same evidence steps that have already been executed in the previous round
        - Only output JSON
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
    """Main synthesis: let LLM produce conclusion JSON."""
    system = (
        "You are a professional data flow analyst, and you are good at tracing the data flow path from the complex code."
        "You can refer to the static.* location results, but the final evidence must come from the source code read by repo.read_* and the local analysis/additional evidence results of the sub Agent."
        "You need to enumerate all possible data flow paths from source to sink as long as you can, even if you later find that you cannot reach the sink."
        "Output must be a strict JSON object."
    )
    user = textwrap.dedent(f"""
        Language: {language}

        source list (JSON):
        {sources_json}

        sink list (JSON):
        {sinks_json}

        repo_map (JSON):
        {repo_map_json}

        Sub Agent local analysis results (JSON array):
        {local_findings_json}

        All rounds of additional evidence results:
        {extra_evidence_json}

        Please output JSON:
        {{
          "reachable": "yes|no|unknown",
          "summary": "A summary of all data flow paths found",
          "paths": [
            [
              {{
                "step": 1,
                "claim": "How does this jump propagate to the next position",
                "evidence": [{{"path":"","start_line":0,"end_line":0,"excerpt":"Must be copied exactly from the source code read by repo.read_* (source code with line numbers)"}}]
              }}
            ]
          ],
          "gaps": ["Why can't it be proven/denied (what type of evidence is missing)"],
          "next_actions": ["Next parallel tasks to do (e.g. search for what symbol, open which file)"]
        }}

        Analysis guidance:
        - There may be strange symbol names in source and sink, such as Attribute or Fstring. Focus on whether the data flow flows to the specified path and line in the sink.
        - When encountering class instantiation, pay attention to the implicit semantic automatic assignment in Python, such as classes that inherit from BaseModel do not need to explicitly define the __init__ method, and the parameters passed during instantiation will be automatically assigned to class attributes;
        - Pay attention to the implicit calls in Python, such as the Pydantic constructor, and the @field_validator modifier trigger modifier parameters.

        Constraints:    
        - paths is an array, containing all the data flow paths found, each path is an array of steps
        - reachable can only be yes if at least one complete path is found
        - Each step in each path must be supported by evidence
        - When a cross-function data flow occurs, you need to pay extra attention to explaining the evidence of this data flow
        - If no paths are found, set paths to an empty array, and set reachable to no or unknown
        - Do not fabricate evidence; if there is no evidence, write unknown and give gaps/next_actions
        - gaps cannot contain content that can be solved by additional evidence
        - next_actions can contain up to 10 tasks to do
        - Only output JSON, do not output any explanation text
    """).strip()
    return PromptPack(system=system, user=user)


class Planner:
    """Main Agent: two LLM calls (plan + synthesis)."""

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
        Produce the original text of the main plan (JSON string, containing steps).
        tools_doc is obtained from registry.get_tools_doc() and passed in by the caller.
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
        """Produce the original text of the main synthesis (JSON string)."""
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
