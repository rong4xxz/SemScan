"""
Data classes and IO helpers: LocationSpec, AgentFinding, load_locations_*, safe_json_loads, finding_to_jsonable.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LocationSpec:
    """Input location description (source/sink): path, line, symbol?, snippet?, note?"""
    path: str
    line: int
    symbol: Optional[str] = None
    snippet: Optional[str] = None
    note: Optional[str] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LocationSpec":
        if "path" not in d or "line" not in d:
            raise ValueError("LocationSpec must contain path and line")
        return LocationSpec(
            path=str(d["path"]),
            line=int(d["line"]),
            symbol=str(d["symbol"]) if d.get("symbol") is not None else None,
            snippet=str(d["snippet"]) if d.get("snippet") is not None else None,
            note=str(d["note"]) if d.get("note") is not None else None,
        )


@dataclass(frozen=True)
class Evidence:
    path: str
    start_line: int
    end_line: int
    excerpt: str


@dataclass(frozen=True)
class QuerySpec:
    """Structured queries in next_queries."""
    type: str  # "ref_query" / "def_query"
    symbol: str
    file: Optional[str] = None
    line_number: Optional[int] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "QuerySpec":
        if "type" not in d or "symbol" not in d:
            raise ValueError("QuerySpec must contain type and symbol")
        return QuerySpec(
            type=str(d["type"]),
            symbol=str(d["symbol"]),
            file=str(d["file"]) if d.get("file") is not None else None,
            line_number=int(d["line_number"]) if d.get("line_number") is not None else None,
        )


@dataclass(frozen=True)
class AgentFinding:
    """Structured output of the sub Agent."""
    role: str
    claim: str
    confidence: float
    evidence: List[Evidence]
    next_queries: List[QuerySpec]
    raw: Optional[Dict[str, Any]] = None


def load_locations_jsonl(text: str) -> List[LocationSpec]:
    """
    Parse JSONL, one JSON object per line.
    Suggested format: {"path":"src/a.py","line":123,"symbol":"user_input","snippet":"x = user_input"}
    Empty lines and lines starting with # are ignored.
    """
    out: List[LocationSpec] = []
    for idx, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSONL line {idx} is not a valid JSON: {raw}") from e
        out.append(LocationSpec.from_dict(obj))
    return out


def load_locations_yaml(text: str) -> List[LocationSpec]:
    """
    Parse YAML rules, read the list of location points from data["rules"].
    Will remove the repository name prefix (first path segment) before path.
    Dependency: PyYAML (pip install pyyaml).
    """
    try:
        import yaml
    except ImportError as e:
        raise ImportError("load_locations_yaml needs PyYAML, please execute pip install pyyaml") from e
    data = yaml.load(text, Loader=yaml.FullLoader)
    if not data or "rules" not in data:
        return []

    def _strip_repo_prefix(item: Dict[str, Any]) -> Dict[str, Any]:
        """Remove the repository name prefix (first path segment) before path, e.g. 'repo/utils/...' -> 'utils/...'"""
        if "path" in item and isinstance(item["path"], str):
            path = item["path"]
            if "/" in path:
                parts = path.split("/", 1)
                if len(parts) == 2:
                    item = dict(item)
                    item["path"] = parts[1]
        return item

    return [LocationSpec.from_dict(_strip_repo_prefix(item)) for item in data["rules"]]


def safe_json_loads(s: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from model output: parse the whole string first, then capture the first {...}."""
    s = s.strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(s[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def finding_to_jsonable(f: AgentFinding) -> Dict[str, Any]:
    """For orchestrator to write to report."""
    return {
        "role": f.role,
        "claim": f.claim,
        "confidence": f.confidence,
        "evidence": [asdict(e) for e in f.evidence],
        "next_queries": [asdict(q) for q in f.next_queries],
        "raw": f.raw,
    }
