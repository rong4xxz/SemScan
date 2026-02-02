"""
Pipeline: PipelineStep, $ref parsing, SkillsPipeline.run.
In run(), execute tools from registry; wrap resolve_refs and fn(**args) in try/except, write results[step_id].error and do not throw.
Convention: tools throw RuntimeError("Error: reason"), capture and write the error message to results and log, do not interrupt the flow.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from example.logging_ import get_logger

from .registry import ToolRegistry

logger = get_logger(__name__)

Ref = str

# $ref description section (not output by registry, used when combining into plan prompt)
REF_BLOCK = """
================================
Important: pipeline combination ($ref references previous results)
================================
You can use {"$ref": "step_id.path.to.value"} in the args of a step to reference the output of a previous step, thus "chaining" multiple tools:
- Basic format: {"$ref": "step_id.path.to.value"}
- Support array index: {"$ref": "step_id.hits[0].path"}
- Constraint: the referenced step must be before the current step (the pipeline executes in order)

Minimum example (first locate method range, then read source code):
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
    """A pipeline step: tool + args. args supports {"$ref": "step_id.path.to.value"}."""
    id: str
    tool: str
    args: Dict[str, Any]


class PipelineError(RuntimeError):
    """$ref parsing or path access error. In run(), capture and write results[step_id].error, do not throw."""
    pass


def _parse_ref(ref: Ref) -> Tuple[str, str]:
    """Parse ref: no dot then (ref, ""); with dot then split into step_id, rest."""
    if "." not in ref:
        return ref, ""
    step_id, rest = ref.split(".", 1)
    return step_id, rest


_INDEX_RE = re.compile(r"(\w+)(\[(\d+)\])?")


def ref_get(results: Mapping[str, Any], ref: Ref) -> Any:
    """Get value from results by ref, support step.field, step.field[0].subfield. Throw PipelineError if failed."""
    step_id, path = _parse_ref(ref)
    if step_id not in results:
        raise PipelineError(f"$ref points to non-existent step: {step_id}")
    cur: Any = results[step_id]
    if not path:
        return cur
    parts = path.split(".")
    for part in parts:
        m = _INDEX_RE.fullmatch(part)
        if not m:
            raise PipelineError(f"$ref format incorrect: {ref}")
        key = m.group(1)
        idx_raw = m.group(3)
        if not isinstance(cur, dict) or key not in cur:
            raise PipelineError(f"$ref field not found: {ref}")
        cur = cur[key]
        if idx_raw is not None:
            if not isinstance(cur, list):
                raise PipelineError(f"$ref expected list but actual is not: {ref}")
            idx = int(idx_raw)
            if idx < 0 or idx >= len(cur):
                raise PipelineError(f"$ref index out of bounds: {ref}")
            cur = cur[idx]
    return cur


def resolve_refs(value: Any, *, results: Mapping[str, Any]) -> Any:
    """Recursively parse {"$ref": "..."} in value. Call ref_get on $ref, may throw PipelineError."""
    if isinstance(value, dict):
        if set(value.keys()) == {"$ref"} and isinstance(value["$ref"], str):
            return ref_get(results, value["$ref"])
        return {k: resolve_refs(v, results=results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(x, results=results) for x in value]
    return value


class SkillsPipeline:
    """
    Execute steps in order; get tools from registry; parse $ref; summarize results.
    In run(), wrap resolve_refs and fn(**filtered_args) in try/except, write results[step_id].error and continue, do not throw.
    """

    def __init__(self, *, registry: ToolRegistry):
        """
        Args:
            registry: tool name → callable object
        """
        self._registry = registry

    def run(self, *, steps: List[PipelineStep]) -> Dict[str, Any]:
        """
        Execute steps in order; for each step: registry.get(step.tool) -> resolve_refs(step.args) -> filter parameters -> fn(**args).
        Unknown tool or get is None: skip the step, results[step_id] = {"tool": step.tool, "error": "tool not found"}.
        resolve_refs throws PipelineError: results[step_id] = {"tool": step.tool, "error": str(e)}, continue.
        fn execution throws Exception: same as above, continue.
        """
        results: Dict[str, Any] = {}
        for step in steps:
            if step.id in results:
                continue
            fn = self._registry.get(step.tool)
            if fn is None:
                results[step.id] = {"tool": step.tool, "error": "tool not found"}
                continue
            try:
                resolved_args = resolve_refs(step.args, results=results)
            except PipelineError as e:
                results[step.id] = {"tool": step.tool, "error": str(e)}
                logger.warning("pipeline step %s (%s) $ref parsing failed: %s", step.id, step.tool, e)
                continue
            if not isinstance(resolved_args, dict):
                results[step.id] = {"tool": step.tool, "error": "resolved_args not dict"}
                logger.warning("pipeline step %s (%s) resolved_args is not dict", step.id, step.tool)
                continue
            sig = inspect.signature(fn)
            valid_params = set(sig.parameters.keys())
            filtered_args = {k: v for k, v in resolved_args.items() if k in valid_params}
            try:
                out = fn(**filtered_args)
                results[step.id] = out
            except RuntimeError as e:
                # Tools throw RuntimeError("Error: reason"), write to results and log, do not interrupt the flow
                err_msg = str(e)
                results[step.id] = {"tool": step.tool, "error": err_msg}
                logger.error("pipeline step %s (%s) tool execution failed: %s", step.id, step.tool, err_msg)
                continue
            except Exception as e:
                results[step.id] = {"tool": step.tool, "error": str(e)}
                logger.error("pipeline step %s (%s) exception: %s", step.id, step.tool, e, exc_info=True)
                continue
        return results
