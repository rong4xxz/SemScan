"""
Build ToolRegistry based on repo_root, register repo/static/gnu tools and descriptions. Used by orchestrator.
"""
from __future__ import annotations

from typing import Optional

from .gnu import GnuSkills
from .registry import ToolRegistry
from .repo import RepoSkills
from .static import StaticSkills

# Tool descriptions (consistent with the tool list in worker/planner prompts, for get_tools_doc)
_REPO_TREE_DESC = """repo.repo_tree(max_entries:int=400): Get the file tree list of the entire repository, used to understand the project structure
  * max_entries: Maximum number of files to return, default 400, suggest to keep it within 1000"""

_LIST_DIR_DESC = """repo.list_dir(rel_dir:str=".", max_entries:int=200, include_files:bool=True, include_dirs:bool=True):
  List the contents of a specified directory, used to explore a specific folder
  * rel_dir: Relative path (e.g. "src" or "tests/cases")
  * max_entries: Maximum number of entries to return, default 200
  * include_files/include_dirs: Whether to include files/directories, boolean values"""

_READ_RANGE_DESC = """repo.read_range(rel_path:str, start_line:int, end_line:int): Read the specified line range of a file
  * rel_path: Relative path (e.g. "main.py" or "src/utils.py")
  * start_line/end_line: Start and end line numbers (counted from 1)"""

_READ_WINDOW_DESC = """repo.read_window(rel_path:str, line:int, window:int=80): Read the context window around the specified line
  * rel_path: Relative path (e.g. "main.py" or "src/utils.py")
  * line: Target line number
  * window: Context window size, default 80 lines"""

_READ_HEAD_DESC = """repo.read_head(rel_path:str, n:int=120): Read the first n lines of a file
  * rel_path: Relative path (e.g. "main.py" or "src/utils.py")
  * n: Number of lines to read, default 120 lines"""

_STATIC_LOCATE_CLASS_DESC = """static.locate_class_or_method(class_name?:str=None, method_name?:str=None): Locate classes/methods in the repository (based on Python AST)
  * class_name: Class name (**if you want to locate class definition, only pass this parameter**)
  * method_name: Method/function name (**if you want to locate method definition, this parameter cannot be None**, if both class_name and method_name are passed, the specified method in the class is located)
  * Note: static tools output is not evidence; must continue to use repo.read_range / repo.read_window to read the code as evidence"""

_STATIC_LOCATE_METHOD_DESC = """static.locate_method_by_line(rel_path:str, line:int): Locate the function/method definition range belonging to the specified line (based on Python AST)
  * rel_path: Relative path (e.g. "main.py" or "src/utils.py")
  * line: Line number (counted from 1)
  * Note: static tools output is not evidence; must continue to use repo.read_range / repo.read_window to read the code as evidence"""

_SEARCH_TEXT_DESC = """repo.search_text(needle:str, max_hits:int=60, case_sensitive:bool=False): Search text in the entire repository
  * needle: String to search (e.g. "import os")
  * max_hits: Maximum number of matches, default 60, suggest to keep it within 100
  * case_sensitive: Whether to case sensitive, default false"""

_GNU_RG_DESC = """gnu.rg(pattern:str, glob?:str, max_hits:int=80, case_sensitive:bool=False): Use ripgrep for advanced regex search
  * pattern: Regex pattern (e.g. "def \\w+" or "class \\w+:")
  * glob: File name pattern (e.g. "*.py" or "test_*.py"), optional
  * max_hits: Maximum number of matches, default 80
  * case_sensitive: Whether to case sensitive, default false"""


def build_registry(
    *,
    repo_root: str,
    language: str = "python",
) -> ToolRegistry:
    """
    Create RepoSkills, StaticSkills, GnuSkills, and register them to ToolRegistry.
    The returned registry can be directly passed to SkillsPipeline and WorkerAgent.
    """
    registry = ToolRegistry()
    repo = RepoSkills(repo_root=repo_root, language=language)
    static = StaticSkills(repo_root=repo_root)
    gnu = GnuSkills(repo_root=repo_root)

    registry.register("repo_structure_tool", "repo.repo_tree", repo.repo_tree, _REPO_TREE_DESC)
    registry.register("repo_structure_tool", "repo.list_dir", repo.list_dir, _LIST_DIR_DESC)
    registry.register("file_reading_tool", "repo.read_range", repo.read_range, _READ_RANGE_DESC)
    registry.register("file_reading_tool", "repo.read_window", repo.read_window, _READ_WINDOW_DESC)
    registry.register("file_reading_tool", "repo.read_head", repo.read_head, _READ_HEAD_DESC)
    registry.register("static_location_tool", "static.locate_class_or_method", static.locate_class_or_method, _STATIC_LOCATE_CLASS_DESC)
    registry.register("static_location_tool", "static.locate_method_by_line", static.locate_method_by_line, _STATIC_LOCATE_METHOD_DESC)
    registry.register("text_search_tool", "repo.search_text", repo.search_text, _SEARCH_TEXT_DESC)
    registry.register("text_search_tool", "gnu.rg", gnu.rg, _GNU_RG_DESC)

    return registry
