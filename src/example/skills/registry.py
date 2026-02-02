"""
Tool registry: tool name → callable object. Support register/get/registered_names, implement pluggable capabilities.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass

import logging

logger = logging.getLogger(__name__)

class NoneToolError(Exception):
    pass

@dataclass(frozen=True)
class ToolSpec:
    """
    Tool specification: name + fn.
    """
    category: str
    name: str
    fn: Callable
    description: str

_TOOLS_DOC_INTRO = "You can only use these tools (do not invent other tools), and each tool's function and parameter description are as follows:\n\n"
_TOOLS_DOC_OUTRO = "\n\nThe tool output will be returned to you by the system after execution, and you can then draw conclusions based on the real output."

class ToolRegistry:
    """Tool name → callable object. Pipeline gets the function to execute by registry.get(step.tool)."""

    def __init__(self) -> None:
        self._store: Dict[str, ToolSpec] = {}

    def register(self, category: str, name: str, fn: Callable[..., Any], description: str) -> None:
        """Register tool: name like "repo.repo_tree", fn is a callable object."""
        if not fn:
            raise NoneToolError("Error: do not register tools without corresponding implementation")
        self._store[name] = ToolSpec(category, name, fn, description)

    def get(self, name: str) -> Optional[Callable]:
        """Get callable object by name, return None if not registered."""
        if not self._store.get(name):
            logger.warning(f"Attempt to call tool {name} but not registered")
            return None
        return self._store.get(name).fn

    @property
    def tools(self) -> List[str]:
        """Return the list of registered tool names."""
        return list(self._store.keys())


    def get_tools_doc(self) -> str:
        """Return the documentation for all tools to LLM (including overview, by category, each tool description, and ending sentence). Does not contain $ref section."""

        res: Dict[str, List[str]] = {}
        for spec in self._store.values():
            res.setdefault(spec.category, []).append(spec.description)
        parts: List[str] = [_TOOLS_DOC_INTRO]
        first = True
        for category, descriptions in res.items():
            if not first:
                parts.append("\n\n")
            first = False
            parts.append(f"# {category}：\n")
            for d in descriptions:
                d = d.rstrip()
                if not d:
                    continue
                # Add "- " prefix to the first line, and the rest of the lines are original (including * parameters, etc.).
                splitted = d.split("\n")
                parts.append("- " + splitted[0] + "\n")
                for line in splitted[1:]:
                    parts.append(line + "\n")
                parts.append("\n")
            # Remove the last extra \n, so that there is only one newline at the end of each category
            if parts[-1] == "\n":
                parts.pop()
        parts.append(_TOOLS_DOC_OUTRO)
        return "".join(parts)
