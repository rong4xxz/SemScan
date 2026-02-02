"""
Static analysis based on Python's built-in ast (only Python).
Methods return dict, to support pipeline $ref (e.g. s0.path, s0.start_line, s0.end_line).
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "dist", "build", "target", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".tox",
}


@dataclass(frozen=True)
class SymbolSpec:
    path: str
    start_line: int
    end_line: int
    kind: str  # "class" | "method" | "function"
    qualname: str


def _to_module_name(rel_path: str) -> str:
    rp = rel_path.replace("\\", "/")
    if rp.endswith(".py"):
        rp = rp[:-3]
    rp = rp.strip("/")
    return rp.replace("/", ".") if rp else ""


class _IndexVisitor(ast.NodeVisitor):
    def __init__(self, *, rel_path: str):
        self.rel_path = rel_path
        self.module = _to_module_name(rel_path)
        self._class_stack: List[str] = []
        self._func_stack: List[str] = []
        self.symbols: List[SymbolSpec] = []

    def _q(self, parts: List[str]) -> str:
        if self.module:
            return self.module + "." + ".".join(parts) if parts else self.module
        return ".".join(parts)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        start = int(getattr(node, "lineno", 1) or 1)
        end = int(getattr(node, "end_lineno", start) or start)
        qn = self._q(self._class_stack + [node.name])
        self.symbols.append(
            SymbolSpec(path=self.rel_path, start_line=start, end_line=end, kind="class", qualname=qn)
        )
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        return self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        return self._visit_func(node)

    def _visit_func(self, node: ast.AST) -> Any:
        name = getattr(node, "name", "<lambda>")
        start = int(getattr(node, "lineno", 1) or 1)
        end = int(getattr(node, "end_lineno", start) or start)
        if self._class_stack:
            qn = self._q(self._class_stack + [name])
            kind = "method"
        else:
            parts = self._func_stack + [name]
            qn = self._q(parts)
            kind = "function"
        self.symbols.append(
            SymbolSpec(path=self.rel_path, start_line=start, end_line=end, kind=kind, qualname=qn)
        )
        self._func_stack.append(name)
        self.generic_visit(node)
        self._func_stack.pop()


class AstStaticSkills:
    """
    AST static analysis (only Python). Support build_index, locate_class_or_method, locate_method_by_line.
    Methods return dict, to support pipeline $ref and results storage.
    """

    def __init__(
        self,
        *,
        repo_root: str,
        exclude_dirs: Optional[Sequence[str]] = None,
        max_file_bytes: int = 2_000_000,
    ):
        self.root = Path(repo_root).resolve()
        self.exclude_dirs = set(exclude_dirs or DEFAULT_EXCLUDE_DIRS)
        self.max_file_bytes = max_file_bytes
        self._built = False
        self._classes_by_name: Dict[str, List[SymbolSpec]] = {}
        self._methods_by_name: Dict[str, List[SymbolSpec]] = {}
        self._methods_by_class_and_name: Dict[Tuple[str, str], List[SymbolSpec]] = {}
        self._file_symbols: Dict[str, List[SymbolSpec]] = {}

    def _iter_py_files(self) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in self.exclude_dirs]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                p = Path(dirpath) / fn
                try:
                    if p.stat().st_size > self.max_file_bytes:
                        continue
                except OSError:
                    continue
                yield p

    def _read_file(self, abs_path: Path) -> str:
        return abs_path.read_text(encoding="utf-8", errors="replace")

    def _parse_file(self, *, abs_path: Path) -> Tuple[str, List[SymbolSpec]]:
        if not abs_path.exists():
            raise RuntimeError(f"Error: file does not exist: {abs_path}")
        try:
            rel_path = str(abs_path.relative_to(self.root)).replace("\\", "/")
        except Exception:
            raise RuntimeError(f"Error: path is not in repo_root: {abs_path}")
        try:
            src = self._read_file(abs_path)
            tree = ast.parse(src, filename=rel_path)
        except SyntaxError as e:
            raise RuntimeError(f"Error: parsing failed (SyntaxError) {rel_path}:{getattr(e, 'lineno', '?')} {e.msg}")
        except Exception as e:
            raise RuntimeError(f"Error: parsing failed ({type(e).__name__}) {rel_path}: {e}")
        v = _IndexVisitor(rel_path=rel_path)
        v.visit(tree)
        return rel_path, v.symbols

    def build_index(self) -> None:
        self._classes_by_name.clear()
        self._methods_by_name.clear()
        self._methods_by_class_and_name.clear()
        self._file_symbols.clear()
        for p in self._iter_py_files():
            try:
                rel_path, symbols = self._parse_file(abs_path=p)
            except RuntimeError:
                continue
            self._file_symbols[rel_path] = symbols
            for s in symbols:
                if s.kind == "class":
                    cls = s.qualname.split(".")[-1]
                    self._classes_by_name.setdefault(cls, []).append(s)
                elif s.kind == "method":
                    m = s.qualname.split(".")[-1]
                    cls = s.qualname.split(".")[-2] if "." in s.qualname else ""
                    self._methods_by_name.setdefault(m, []).append(s)
                    if cls:
                        self._methods_by_class_and_name.setdefault((cls, m), []).append(s)
                elif s.kind == "function":
                    m = s.qualname.split(".")[-1]
                    self._methods_by_name.setdefault(m, []).append(s)
        self._built = True

    def _spec_to_hit(self, s: SymbolSpec) -> Dict[str, Any]:
        return {
            "path": s.path,
            "start_line": s.start_line,
            "end_line": s.end_line,
            "kind": s.kind,
            "qualname": s.qualname,
        }

    def locate_class_or_method(
        self,
        *,
        class_name: Optional[str] = None,
        method_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return dict: ok, hits, and the path/start_line/end_line of the first hit (for $ref)."""
        if not self._built:
            self.build_index()
        hits_list: List[SymbolSpec] = []
        if class_name and method_name:
            hits_list = self._methods_by_class_and_name.get((class_name, method_name), [])
            if not hits_list:
                raise RuntimeError(f"Error: {class_name}.{method_name} not found")
        elif class_name:
            hits_list = self._classes_by_name.get(class_name, [])
            if not hits_list:
                hits_list = self._methods_by_name.get(class_name, [])
            if not hits_list:
                raise RuntimeError(f"Error: {class_name} class not found")
        elif method_name:
            hits_list = self._methods_by_name.get(method_name, [])
            if not hits_list:
                hits_list = self._classes_by_name.get(method_name, [])
            if not hits_list:
                raise RuntimeError(f"Error: {method_name} method not found")
        else:
            raise RuntimeError("Error: class_name or method_name not provided")
        hits = [self._spec_to_hit(s) for s in hits_list]
        out: Dict[str, Any] = {
            "tool": "static.locate_class_or_method",
            "ok": True,
            "hits": hits,
        }
        if hits:
            out["path"] = hits[0]["path"]
            out["start_line"] = hits[0]["start_line"]
            out["end_line"] = hits[0]["end_line"]
        return out

    def locate_method_by_line(self, *, rel_path: str, line: int) -> Dict[str, Any]:
        """Return dict: path, start_line, end_line (for $ref), and found/ok."""
        rel_path = str(rel_path).replace("\\", "/").lstrip("/")
        abs_path = (self.root / rel_path).resolve()
        if not abs_path.exists():
            raise RuntimeError(f"Error: {rel_path} file not found")
        symbols = self._file_symbols.get(rel_path)
        if symbols is None:
            try:
                _, symbols = self._parse_file(abs_path=abs_path)
            except RuntimeError as e:
                raise e
            self._file_symbols[rel_path] = symbols
        line = int(line)
        candidates = [
            s for s in symbols
            if s.kind in ("method", "function") and s.start_line <= line <= s.end_line
        ]
        if not candidates:
            return {
                "tool": "static.locate_method_by_line",
                "ok": True,
                "found": False,
                "path": rel_path,
                "start_line": -1,
                "end_line": -1,
            }
        s = min(candidates, key=lambda x: (x.end_line - x.start_line, -x.start_line))
        return {
            "tool": "static.locate_method_by_line",
            "ok": True,
            "found": True,
            "path": s.path,
            "start_line": s.start_line,
            "end_line": s.end_line,
            "kind": s.kind,
            "qualname": s.qualname,
        }


StaticSkills = AstStaticSkills  # Compatibility name
