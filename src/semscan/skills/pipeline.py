"""
Pipeline primitives: PipelineStep, $ref resolution, and SkillsPipeline.run.
run() fetches tools from the registry and wraps resolve_refs and fn(**args) in try/except;
failures are written to results[step_id].error instead of being raised.
Convention: tools raise RuntimeError("Error: reason"), which is captured, logged,
and stored in results without interrupting the pipeline.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from semscan.logging_ import get_logger

from .registry import ToolRegistry

logger = get_logger(__name__)

Ref = str

# $ref documentation block (not produced by registry; appended to plan prompts)
REF_BLOCK = """
================================
Important: pipeline composition ($ref references to previous results)
================================
You can use {"$ref": "step_id.path.to.value"} inside a step's args to reference
the output of an earlier step and chain multiple tools together:
- Basic format: {"$ref": "step_id.field.path"}
- Array indexing is supported: {"$ref": "step_id.hits[0].path"}
- Constraint: the referenced step must come before the current step (the pipeline runs in order)

Minimal semscan (locate a method range first, then read the source):
{
  "role": "pipeline_plan",
  "steps": [
    {"id": "s0", "tool": "static.locate_method_by_line", "args": {"rel_path": "a/b.py", "line": 123}},
    {"id": "r0", "tool": "repo.read_range", "args": {"rel_path": {"$ref": "s0.path"}, "start_line": {"$ref": "s0.start_line"}, "end_line": {"$ref": "s0.end_line"}}}
  ]
}
""".strip()


@dataclass(frozen=True)
class PipelineStep:
    """One pipeline step: tool + args. Args support {"$ref": "step_id.path.to.value"}."""
    id: str
    tool: str
    args: Dict[str, Any]


class PipelineError(RuntimeError):
    """Raised on $ref resolution or path access errors; run() should capture and store it."""
    pass


def _parse_ref(ref: Ref) -> Tuple[str, str]:
    """Parse a ref: without a dot returns (ref, ""), otherwise splits at the first dot."""
    if "." not in ref:
        return ref, ""
    step_id, rest = ref.split(".", 1)
    return step_id, rest


_INDEX_RE = re.compile(r"(\w+)(\[(\d+)\])?")


def ref_get(results: Mapping[str, Any], ref: Ref) -> Any:
    """Read a value from results by ref, supporting step.field and step.field[0].subfield."""
    step_id, path = _parse_ref(ref)
    if step_id not in results:
        raise PipelineError(f"$ref points to a non-existent step: {step_id}")
    cur: Any = results[step_id]
    if not path:
        return cur
    parts = path.split(".")
    for part in parts:
        m = _INDEX_RE.fullmatch(part)
        if not m:
            raise PipelineError(f"Invalid $ref format: {ref}")
        key = m.group(1)
        idx_raw = m.group(3)
        if not isinstance(cur, dict) or key not in cur:
            raise PipelineError(f"$ref field not found: {ref}")
        cur = cur[key]
        if idx_raw is not None:
            if not isinstance(cur, list):
                raise PipelineError(f"$ref expected a list but got something else: {ref}")
            idx = int(idx_raw)
            if idx < 0 or idx >= len(cur):
                raise PipelineError(f"$ref index out of range: {ref}")
            cur = cur[idx]
    return cur


def resolve_refs(value: Any, *, results: Mapping[str, Any]) -> Any:
    """Recursively resolve {"$ref": "..."} within value; may raise PipelineError."""
    if isinstance(value, dict):
        if set(value.keys()) == {"$ref"} and isinstance(value["$ref"], str):
            return ref_get(results, value["$ref"])
        return {k: resolve_refs(v, results=results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(x, results=results) for x in value]
    return value


class SkillsPipeline:
    """
    Execute steps in order, fetch tools from the registry, resolve $ref values,
    and aggregate results.
    run() catches errors from resolve_refs and fn(**filtered_args), writes them to
    results[step_id].error, and continues without raising.
    """

    def __init__(self, *, registry: ToolRegistry):
        """
        Args:
            registry: Maps tool names to callables
        """
        self._registry = registry

    def run(self, *, steps: List[PipelineStep]) -> Dict[str, Any]:
        """
        Execute steps in order. For each step:
        registry.get(step.tool) -> resolve_refs(step.args) -> filter parameters -> fn(**args).
        Unknown tools or None results are skipped with
        {"tool": step.tool, "error": "tool does not exist"}.
        PipelineError from resolve_refs and exceptions from fn are stored the same way and execution continues.
        """
        results: Dict[str, Any] = {}
        for step in steps:
            if step.id in results:
                continue
            fn = self._registry.get(step.tool)
            if fn is None:
                results[step.id] = {"tool": step.tool, "error": "tool does not exist"}
                continue
            try:
                resolved_args = resolve_refs(step.args, results=results)
            except PipelineError as e:
                results[step.id] = {"tool": step.tool, "error": str(e)}
                logger.warning("pipeline step %s (%s) failed to resolve $ref: %s", step.id, step.tool, e)
                continue
            if not isinstance(resolved_args, dict):
                results[step.id] = {"tool": step.tool, "error": "resolved_args not dict"}
                logger.warning("pipeline step %s (%s) resolved_args is not a dict", step.id, step.tool)
                continue
            sig = inspect.signature(fn)
            valid_params = set(sig.parameters.keys())
            filtered_args = {k: v for k, v in resolved_args.items() if k in valid_params}
            try:
                out = fn(**filtered_args)
                results[step.id] = out
            except RuntimeError as e:
                # Tools are expected to raise RuntimeError("Error: reason"); store and log without interrupting the pipeline.
                err_msg = str(e)
                results[step.id] = {"tool": step.tool, "error": err_msg}
                logger.error("pipeline step %s (%s) tool execution failed: %s", step.id, step.tool, err_msg)
                continue
            except Exception as e:
                results[step.id] = {"tool": step.tool, "error": str(e)}
                logger.error("pipeline step %s (%s) exception: %s", step.id, step.tool, e, exc_info=True)
                continue
        return results
