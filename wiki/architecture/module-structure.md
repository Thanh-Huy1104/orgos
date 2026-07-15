# Module Structure

## Overview
This wiki documents the architecture and decisions for the orgos project.

## Layout
- `orgos/` - main source package
  - `agile/` - agile workflow engine (board, sprint, rubric, etc.)
  - `spawn/` - agent spawning and persona management
  - `mcps/` - MCP server implementations
  - `tools/` - tool implementations (bash, github, etc.)
  - `subagents/` - multi-agent orchestration
- `tests/` - test suite mirroring source structure
- `wiki/` - documentation and decision records
