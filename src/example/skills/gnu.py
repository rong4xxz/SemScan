"""
GNU/CLI tool wrapper: ripgrep (rg).
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .repo import FileHit


class GnuSkills:
    """
    Wrap ripgrep (rg) as Skills. No shell, parameter whitelist, to avoid injection.
    """

    def __init__(self, *, repo_root: str):
        self.root = Path(repo_root).resolve()

    def _require_bin(self, name: str) -> str:
        p = shutil.which(name)
        if not p:
            raise RuntimeError(f"Error: executable file {name} not found (please install and try again)")
        return p

    def rg(
        self,
        *,
        pattern: str,
        glob: Optional[str] = None,
        max_hits: int = 80,
        case_sensitive: bool = False,
    ) -> Dict[str, Any]:
        """
        Use ripgrep to search, return structured hit list.
        Return dict: tool, pattern, hits, truncated, exit_code, stderr.
        """
        rg_bin = self._require_bin("rg")
        cmd: List[str] = [
            rg_bin,
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            "--max-count",
            str(max(1, max_hits)),
        ]
        if not case_sensitive:
            cmd.append("--ignore-case")
        if glob:
            cmd.extend(["--glob", glob])
        cmd.append(pattern)
        cmd.append(str(self.root))
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        hits: List[FileHit] = []
        for raw in stdout.splitlines():
            first = raw.find(":")
            if first <= 0:
                continue
            path_part = raw[:first]
            rest = raw[first + 1 :]
            second = rest.find(":")
            if second <= 0:
                continue
            line_part = rest[:second]
            excerpt = rest[second + 1 :].strip()
            try:
                line = int(line_part)
            except ValueError:
                continue
            try:
                rel = str(Path(path_part).resolve().relative_to(self.root))
            except Exception:
                rel = path_part
            hits.append(FileHit(path=rel, line=line, excerpt=excerpt[:400]))
        return {
            "tool": "gnu.rg",
            "pattern": pattern,
            "hits": [asdict(h) for h in hits],
            "truncated": len(hits) >= max_hits,
            "exit_code": proc.returncode,
            "stderr": stderr.strip(),
        }
