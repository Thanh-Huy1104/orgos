# Wiki + Board Substrate — Implementation Plan (Plan 3)

> **Status:** Executed 2026-07-13. Retrospective document.

**Goal:** Build the persistent memory + coordination substrate. Agents can read the wiki via MCP; PO can draft stories; team refines; stories move DRAFT→REFINEMENT→READY→IN_PROGRESS→REVIEW→DONE; agents pull from top of READY.

**Architecture:** A new filesystem-backed wiki MCP server exposes five tools (`wiki_list`, `wiki_read`, `wiki_grep`, `wiki_recent`, `wiki_write`) following the existing `orgos/mcps/` pattern. A GitHub-Issues-as-board tool implements the column flow with label-based state encoding. Pure READY gate logic in `orgos/agile/board.py` enforces signoff and size-cap checks without depending on GitHub.

## File map

| Path | Action | Purpose |
|------|--------|---------|
| `wiki/INDEX.md` | Created | Wiki index with conventions |
| `wiki/DECISIONS.md` | Created | Chronological decision log |
| `wiki/architecture/INDEX.md` | Created | Architecture decisions index |
| `wiki/business/INDEX.md` | Created | Business context index |
| `wiki/ADRs/INDEX.md` | Created | Architecture Decision Records index |
| `orgos/mcps/wiki_mcp.py` | Created | MCP server: list, read, grep, recent(n), write |
| `orgos/mcps/wiki.py` | Created | MCP factory: `create_wiki_mcp()` |
| `orgos/agile/board.py` | Created | READY gate: `check_ready_gate()`, `story_fits_size_caps()` |
| `orgos/tools/github_board.py` | Created | GitHub Issues board tool (10 actions) |

## Key interfaces

```python
# Wiki MCP tools
wiki_list(path="")        -> list[{name, type, size, modified}]
wiki_read(path, max_lines) -> {path, lines, truncated, content}
wiki_grep(pattern, path?) -> [{file, line, text}]
wiki_recent(n=10)         -> [{file, size, modified}]
wiki_write(path, content, mode="overwrite"|"append") -> {path, size, modified}

# Board tool actions
draft_story(title, body)                    -> issue with state:draft
read_story(number)                          -> normalised issue
refine_story(number, role, concern)         -> comment with role label
signoff_story(number, role)                 -> refined:<role> label
mark_ready(number, estimated_files, loc)    -> state:ready (after gate check)
list_ready()                                -> ready items sorted by priority
pull_top()                                  -> top ready -> in_progress
update_status(number, state)                -> move between columns
add_comment(number, body)                   -> comment on issue
list_labels()                               -> all board labels

# READY gate
check_ready_gate(title, acceptance_criteria, estimated_files, estimated_loc, role_signoffs) -> ReadyGateResult
story_fits_size_caps(files, loc) -> (ok, reason)
```

## Verification

- 27 wiki MCP tests pass (list/read/grep/recent/write + tool descriptors)
- 13 board gate logic tests pass
- 21 GitHub board tool tests pass (all 10 actions with mocked GitHub API)
- Wiki scaffold reads correctly via MCP functions
