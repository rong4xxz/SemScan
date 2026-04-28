"""
Repository read operations: RepoSkills and FileHit.
Returns dict objects to support pipeline $ref, following semscan.skills.repo.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

# Aligned with semscan.config; semscan does not depend on semscan.
LANG_EXTS: Dict[str, Tuple[str, ...]] = {
    "python": (".py",),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
    "go": (".go",),
    "java": (".java",),
    "c": (".c", ".h"),
    "cpp": (".cc", ".cpp", ".cxx", ".hpp", ".hxx", ".hh"),
    "rust": (".rs",),
}

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "dist", "build", "target", "__pycache__", ".pytest_cache", ".tox",
    ".coverage", "htmlcov", ".mypy_cache", ".eggs", ".DS_Store", "Thumbs.db",
}


@dataclass(frozen=True)
class FileHit:
    path: str
    line: int
    excerpt: str


class RepoSkills:
    """
    Repository I/O plus text search. Methods return dict objects to support
    pipeline $ref and evidence extraction.
    On error, raises RuntimeError("Error: reason"), which pipeline stores in results[step_id].error.
    """

    def __init__(
        self,
        *,
        repo_root: str,
        language: str = "python",
        exclude_dirs: Optional[Sequence[str]] = None,
        max_file_bytes: int = 2_000_000,
    ):
        self.root = Path(repo_root).resolve()
        self.language = language.lower()
        self.exts = LANG_EXTS.get(self.language, (".py",))
        self.exclude_dirs = set(exclude_dirs or DEFAULT_EXCLUDE_DIRS)
        self.max_file_bytes = max_file_bytes

    def _should_include(self, p: Path) -> bool:
        if not p.is_file():
            return False
        if self.exts and p.suffix.lower() not in self.exts:
            return False
        try:
            if p.stat().st_size > self.max_file_bytes:
                return False
        except OSError:
            return False
        return True

    def _add_line_numbers(self, lines: List[str], start_line: int) -> str:
        numbered = [f"{start_line + i}: {line}" for i, line in enumerate(lines)]
        return "\n".join(numbered)

    def iter_source_files(self) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in self.exclude_dirs]
            for fn in filenames:
                p = Path(dirpath) / fn
                if self._should_include(p):
                    yield p

    def repo_tree(self, *, max_entries: int = 400) -> Dict[str, object]:
        out: List[str] = []
        for p in self.iter_source_files():
            try:
                rel_path = str(p.relative_to(self.root))
            except Exception as e:
                raise RuntimeError(f"Error: failed to compute relative path for path={p}: {e}")
            out.append(rel_path)
            if len(out) >= max_entries:
                break
        return {"tool": "repo.repo_tree", "max_entries": max_entries, "files": out}

    def list_dir(
        self,
        *,
        rel_dir: str = ".",
        max_entries: int = 200,
        include_files: bool = True,
        include_dirs: bool = True,
    ) -> Dict[str, object]:
        abs_dir = (self.root / rel_dir).resolve()
        if self.root not in abs_dir.parents and abs_dir != self.root:
            raise RuntimeError(f"Error: list_dir path escapes repo root: {rel_dir}")
        if not abs_dir.exists():
            raise RuntimeError(f"Error: list_dir path does not exist: {rel_dir}")
        if not abs_dir.is_dir():
            raise RuntimeError(f"Error: list_dir target is not a directory: {rel_dir}")
        try:
            children = sorted(abs_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as e:
            raise RuntimeError(f"Error: list_dir could not read directory {rel_dir}: {e}")
        out: List[str] = []
        for p in children:
            if p.name in self.exclude_dirs:
                continue
            if p.is_dir() and not include_dirs:
                continue
            if p.is_file() and not include_files:
                continue
            try:
                rel = str(p.relative_to(self.root))
            except Exception as e:
                raise RuntimeError(f"Error: list_dir failed to compute relative path: {e}")
            out.append(rel)
            if len(out) >= max(1, max_entries):
                break
        return {
            "tool": "repo.list_dir",
            "rel_dir": rel_dir,
            "max_entries": max_entries,
            "include_files": include_files,
            "include_dirs": include_dirs,
            "items": out,
        }

    def read_head(self, *, rel_path: str, n: int = 120) -> Dict[str, object]:
        abs_path = (self.root / rel_path).resolve()
        if self.root not in abs_path.parents and abs_path != self.root:
            raise RuntimeError(f"Error: read_head path escapes repo root: {rel_path}")
        if not abs_path.exists():
            raise RuntimeError(f"Error: read_head file does not exist: {rel_path}")
        n = max(1, n)
        lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        end = min(len(lines), n)
        text = self._add_line_numbers(lines[:end], start_line=1)
        return {
            "tool": "repo.read_head",
            "path": rel_path,
            "start_line": 1,
            "end_line": end,
            "text": text,
        }

    def read_range(self, *, rel_path: str, start_line: int, end_line: int) -> Dict[str, object]:
        abs_path = (self.root / rel_path).resolve()
        if self.root not in abs_path.parents and abs_path != self.root:
            raise RuntimeError(f"Error: read_range path escapes repo root: {rel_path}")
        if not abs_path.exists():
            raise RuntimeError(f"Error: read_range file does not exist: {rel_path}")
        lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start_line)
        end = min(len(lines), max(start, end_line))
        chunk = lines[start - 1 : end]
        text = self._add_line_numbers(chunk, start_line=start)
        return {
            "tool": "repo.read_range",
            "path": rel_path,
            "start_line": start,
            "end_line": end,
            "text": text,
        }

    def read_window(self, *, rel_path: str, line: int, window: int = 80) -> Dict[str, object]:
        start = max(1, line - window)
        end = line + window
        abs_path = (self.root / rel_path).resolve()
        if not abs_path.exists():
            raise RuntimeError(f"Error: read_window file does not exist: {rel_path}")
        total = len(abs_path.read_text(encoding="utf-8", errors="replace").splitlines())
        end = min(total, end)
        text = self.read_range(rel_path=rel_path, start_line=start, end_line=end)["text"]
        return {
            "tool": "repo.read_window",
            "path": rel_path,
            "line": line,
            "start_line": start,
            "end_line": end,
            "text": text,
        }

    def search_text(
        self,
        *,
        needle: str,
        max_hits: int = 60,
        case_sensitive: bool = False,
    ) -> Dict[str, object]:
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(re.escape(needle), flags)
        hits: List[Dict[str, object]] = []
        for p in self.iter_source_files():
            rel = str(p.relative_to(self.root))
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, ln in enumerate(lines, start=1):
                if pattern.search(ln):
                    hits.append({"path": rel, "line": i, "excerpt": ln[:400]})
                    if len(hits) >= max_hits:
                        return {"tool": "repo.search_text", "needle": needle, "hits": hits}
        return {"tool": "repo.search_text", "needle": needle, "hits": hits}
