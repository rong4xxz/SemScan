"""
Tool registry: maps tool names to callables. Supports register/get/tool listing
for pluggable capabilities.
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
    Tool specification: category, name, function, and description.
    """
    category: str
    name: str
    fn: Callable
    description: str

_TOOLS_DOC_INTRO = "These are the only tools available to you (do not invent other tools). Their purpose and parameters are:\n\n"
_TOOLS_DOC_OUTRO = "\n\nTool outputs will be executed by the system and returned to you. Base your conclusions only on those real outputs."

class ToolRegistry:
    """Map tool names to callables. Pipeline executes tools via ``registry.get(step.tool)``."""

    def __init__(self) -> None:
        self._store: Dict[str, ToolSpec] = {}

    def register(self, category: str, name: str, fn: Callable[..., Any], description: str) -> None:
        """Register a tool, e.g. name ``repo.repo_tree`` with a callable implementation."""
        if not fn:
            raise NoneToolError("Error: cannot register a tool without an implementation")
        self._store[name] = ToolSpec(category, name, fn, description)

    def get(self, name: str) -> Optional[Callable]:
        """Get a callable by name; return None if it is not registered."""
        if not self._store.get(name):
            logger.warning(f"Attempted to call unregistered tool {name}")
            return None
        return self._store.get(name).fn

    @property
    def tools(self) -> List[str]:
        """Return the list of registered tool names."""
        return list(self._store.keys())


    def get_tools_doc(self) -> str:
        """Return the full tool documentation shown to the LLM, excluding the $ref block."""

        res: Dict[str, List[str]] = {}
        for spec in self._store.values():
            res.setdefault(spec.category, []).append(spec.description)
        parts: List[str] = [_TOOLS_DOC_INTRO]
        first = True
        for category, descriptions in res.items():
            if not first:
                parts.append("\n\n")
            first = False
            parts.append(f"# {category}:\n")
            for d in descriptions:
                d = d.rstrip()
                if not d:
                    continue
                # Add "- " to the first line and keep the rest unchanged to match semscan formatting.
                splitted = d.split("\n")
                parts.append("- " + splitted[0] + "\n")
                for line in splitted[1:]:
                    parts.append(line + "\n")
                parts.append("\n")
            # Drop the last extra newline so each category ends with exactly one blank line.
            if parts[-1] == "\n":
                parts.pop()
        parts.append(_TOOLS_DOC_OUTRO)
        return "".join(parts)
