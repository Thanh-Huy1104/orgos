"""Filesystem tools for agents — Read / Write / Edit locked to a worktree.

Contrast with BashTool: BashTool works via subprocess + heredoc, which forces
the agent to `cat > file <<EOF ... EOF` even for a one-line change. That's
fine for small greenfield modules but ruins any edit to a large existing file.

These tools operate in-process on files inside a locked working directory:

  - ReadFileTool  → return file contents (with optional line range)
  - WriteFileTool → replace or create a file
  - EditFileTool  → find + replace within an existing file (safer than rewrite)

All three refuse operations outside `default_working_dir` to enforce the
worktree sandbox. Follow the same tool_category / GatedToolBase pattern as
BashTool so tier policy applies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from orgos.spawn.governance.toolbase import GatedToolBase


# ── path helpers ────────────────────────────────────────────────────────

def _resolve_inside(root: Path, rel_path: str) -> Optional[Path]:
    """Resolve a user path against root; return None if it escapes."""
    try:
        p = (root / rel_path).resolve()
        root_r = root.resolve()
        # Path.is_relative_to only exists on 3.9+, we're on 3.11+
        if not p.is_relative_to(root_r):
            return None
        return p
    except Exception:
        return None


# ── ReadFileTool ────────────────────────────────────────────────────────

class _ReadInput(BaseModel):
    path: str = Field(..., description="Relative path to the file, from the worktree root.")
    start_line: int = Field(default=1, description="1-indexed first line to include (default 1).")
    max_lines: int = Field(default=400, description="Max lines to return (default 400).")


class ReadFileTool(GatedToolBase):
    """Read a text file inside the worktree.

    Prefer this to `cat` because it caps line count (protects context) and
    can return a specific range for large files.
    """

    name: str = "read_file"
    description: str = (
        "Read a text file from the worktree. Returns the specified line range "
        "(default first 400 lines). Prefer this to `cat` on large files. "
        "Inputs: path (str), start_line (int, default 1), max_lines (int, default 400)."
    )
    args_schema: type[BaseModel] = _ReadInput
    tool_category: str = "read"
    default_working_dir: Optional[str] = Field(
        default=None,
        description="Absolute path — reads are locked to this directory.",
        exclude=True,
    )

    def _run(self, path: str, start_line: int = 1, max_lines: int = 400) -> str:
        if not self._check_gate({"path": path}):
            return f"DENIED: read_file on {path!r} not approved."
        root = Path(self.default_working_dir or ".")
        p = _resolve_inside(root, path)
        if p is None:
            return f"ERROR: path escapes worktree root: {path}"
        if not p.exists():
            return f"ERROR: file not found: {path}"
        if p.is_dir():
            return f"ERROR: path is a directory (use bash `ls`): {path}"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"ERROR: {e}"
        lines = text.splitlines()
        total = len(lines)
        start = max(1, int(start_line))
        end = min(total, start - 1 + max(1, int(max_lines)))
        window = lines[start - 1:end]
        truncated = end < total
        header = f"# {path} (lines {start}-{end} of {total}{', truncated' if truncated else ''})\n"
        body = "\n".join(f"{start + i:4d}  {line}" for i, line in enumerate(window))
        return header + body


# ── WriteFileTool ───────────────────────────────────────────────────────

class _WriteInput(BaseModel):
    path: str = Field(..., description="Relative path to the file, from the worktree root.")
    content: str = Field(..., description="Full new file contents (replaces any existing).")


class WriteFileTool(GatedToolBase):
    """Create or overwrite a file inside the worktree.

    Use this for NEW files or when you genuinely want to replace an entire file.
    For narrow edits to existing files, use `edit_file` instead — it's less
    destructive and preserves surrounding content.
    """

    name: str = "write_file"
    description: str = (
        "Create a new file or fully overwrite an existing one. "
        "Prefer `edit_file` for narrow changes to existing files. "
        "Inputs: path (str), content (str)."
    )
    args_schema: type[BaseModel] = _WriteInput
    tool_category: str = "sandbox"
    default_working_dir: Optional[str] = Field(
        default=None,
        description="Absolute path — writes are locked to this directory.",
        exclude=True,
    )

    def _run(self, path: str, content: str) -> str:
        if not self._check_gate({"path": path}):
            return f"DENIED: write_file on {path!r} not approved."
        root = Path(self.default_working_dir or ".")
        p = _resolve_inside(root, path)
        if p is None:
            return f"ERROR: path escapes worktree root: {path}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as e:
            return f"ERROR: {e}"
        size = p.stat().st_size
        return f"OK: wrote {path} ({size} bytes, {len(content.splitlines())} lines)"


# ── EditFileTool ────────────────────────────────────────────────────────

class _EditInput(BaseModel):
    path: str = Field(..., description="Relative path to the file, from the worktree root.")
    old: str = Field(..., description="Exact literal text to find (must appear exactly once).")
    new: str = Field(..., description="Text to replace `old` with.")


class EditFileTool(GatedToolBase):
    """Find + replace a unique literal string inside an existing file.

    Fails if `old` is not found OR if it appears more than once — that
    ambiguity would risk clobbering the wrong occurrence. When you need to
    change multiple identical spans, either widen `old` to include enough
    surrounding context to make it unique, or use `write_file` to overwrite
    the whole file.
    """

    name: str = "edit_file"
    description: str = (
        "Find + replace a unique literal string in an existing file. "
        "The `old` string must appear EXACTLY ONCE in the file — otherwise "
        "the tool refuses (ambiguous). Widen `old` with surrounding context to "
        "disambiguate. Use this for narrow edits instead of rewriting whole files. "
        "Inputs: path (str), old (str), new (str)."
    )
    args_schema: type[BaseModel] = _EditInput
    tool_category: str = "sandbox"
    default_working_dir: Optional[str] = Field(
        default=None,
        description="Absolute path — edits are locked to this directory.",
        exclude=True,
    )

    def _run(self, path: str, old: str, new: str) -> str:
        if not self._check_gate({"path": path}):
            return f"DENIED: edit_file on {path!r} not approved."
        root = Path(self.default_working_dir or ".")
        p = _resolve_inside(root, path)
        if p is None:
            return f"ERROR: path escapes worktree root: {path}"
        if not p.exists():
            return f"ERROR: file not found (use write_file to create): {path}"
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            return f"ERROR: {e}"
        count = text.count(old)
        if count == 0:
            return (
                f"ERROR: `old` string not found in {path}. Check whitespace / "
                f"line endings. Tip: use `read_file` first to grab the exact text."
            )
        if count > 1:
            return (
                f"ERROR: `old` string appears {count} times in {path} — ambiguous. "
                f"Widen it with surrounding context so it appears exactly once."
            )
        new_text = text.replace(old, new, 1)
        try:
            p.write_text(new_text, encoding="utf-8")
        except OSError as e:
            return f"ERROR: {e}"
        delta_lines = len(new.splitlines()) - len(old.splitlines())
        return (
            f"OK: edited {path} (1 replacement, "
            f"{'+' if delta_lines >= 0 else ''}{delta_lines} lines)"
        )
