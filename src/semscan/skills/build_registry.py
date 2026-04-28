"""
Build a ToolRegistry from repo_root and register repo/static/gnu tools plus their
descriptions for orchestrator use.
"""
from __future__ import annotations

from typing import Optional

from .gnu import GnuSkills
from .registry import ToolRegistry
from .repo import RepoSkills
from .static_ast import AstStaticSkills

# Tool descriptions used by get_tools_doc; kept consistent with worker/planner prompts.
_REPO_TREE_DESC = """repo.repo_tree(max_entries:int=400): Get the file tree for the entire repository to understand the project structure
  * max_entries: Maximum number of files to return, default 400, recommended <= 1000"""

_LIST_DIR_DESC = """repo.list_dir(rel_dir:str=".", max_entries:int=200, include_files:bool=True, include_dirs:bool=True):
  List the contents of a directory to explore a specific folder
  * rel_dir: Relative path (for semscan "src" or "tests/cases")
  * max_entries: Maximum number of entries to return, default 200
  * include_files/include_dirs: Whether to include files/directories, boolean values"""

_READ_RANGE_DESC = """repo.read_range(rel_path:str, start_line:int, end_line:int): Read a specific line range from a file
  * rel_path: Relative file path (for semscan "main.py" or "src/utils.py")
  * start_line/end_line: Start and end line numbers (1-based)"""

_READ_WINDOW_DESC = """repo.read_window(rel_path:str, line:int, window:int=80): Read a context window around a target line
  * rel_path: Relative file path
  * line: Target line number
  * window: Number of context lines above and below, default 80"""

_READ_HEAD_DESC = """repo.read_head(rel_path:str, n:int=120): Read the first n lines of a file
  * rel_path: Relative file path
  * n: Number of lines to read, default 120"""

_STATIC_LOCATE_CLASS_DESC = """static.locate_class_or_method(class_name?:str=None, method_name?:str=None): Locate a class/method in the repository (based on Python AST)
  * class_name: Class name (**pass only this parameter if you want to locate a class definition**)
  * method_name: Method/function name (**must not be None if you want to locate a method definition**; if both class_name and method_name are provided, it locates the given method inside the class)
  * Note: static tool output is not evidence; you must continue with repo.read_range / repo.read_window to read the original code as evidence"""

_STATIC_LOCATE_METHOD_DESC = """static.locate_method_by_line(rel_path:str, line:int): Locate the function/method definition range containing a given line (based on Python AST)
  * rel_path: Relative file path
  * line: Line number (1-based)
  * Note: static tool output is not evidence; you must continue with repo.read_range / repo.read_window to read the original code as evidence"""

_SEARCH_TEXT_DESC = """repo.search_text(needle:str, max_hits:int=60, case_sensitive:bool=False): Search for text across the repository
  * needle: String to search for (for semscan "import os")
  * max_hits: Maximum number of matches, default 60, recommended <= 100
  * case_sensitive: Whether the search is case-sensitive, default false"""

_GNU_RG_DESC = """gnu.rg(pattern:str, glob?:str, max_hits:int=80, case_sensitive:bool=False): Use ripgrep for advanced regex search
  * pattern: Regular expression (for semscan "def \\w+" or "class \\w+:")
  * glob: Filename glob (for semscan "*.py" or "test_*.py"), optional
  * max_hits: Maximum number of matches, default 80
  * case_sensitive: Whether the search is case-sensitive, default false"""


def build_registry(
    *,
    repo_root: str,
    language: str = "python",
) -> ToolRegistry:
    """
    Create RepoSkills, AstStaticSkills, and GnuSkills, then register them in the ToolRegistry.
    The returned registry can be passed directly to SkillsPipeline and WorkerAgent.
    """
    registry = ToolRegistry()
    repo = RepoSkills(repo_root=repo_root, language=language)
    static = AstStaticSkills(repo_root=repo_root)
    gnu = GnuSkills(repo_root=repo_root)

    registry.register("Repository Structure Tools", "repo.repo_tree", repo.repo_tree, _REPO_TREE_DESC)
    registry.register("Repository Structure Tools", "repo.list_dir", repo.list_dir, _LIST_DIR_DESC)
    registry.register("File Reading Tools", "repo.read_range", repo.read_range, _READ_RANGE_DESC)
    registry.register("File Reading Tools", "repo.read_window", repo.read_window, _READ_WINDOW_DESC)
    registry.register("File Reading Tools", "repo.read_head", repo.read_head, _READ_HEAD_DESC)
    registry.register("Static Location Tools", "static.locate_class_or_method", static.locate_class_or_method, _STATIC_LOCATE_CLASS_DESC)
    registry.register("Static Location Tools", "static.locate_method_by_line", static.locate_method_by_line, _STATIC_LOCATE_METHOD_DESC)
    registry.register("Text Search Tools", "repo.search_text", repo.search_text, _SEARCH_TEXT_DESC)
    registry.register("Text Search Tools", "gnu.rg", gnu.rg, _GNU_RG_DESC)

    return registry
