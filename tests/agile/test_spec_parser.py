"""Tests for the spec-file parser — extracts story blocks from a markdown PRD."""

from __future__ import annotations

from orgos.agile.spec_parser import (
    parse_spec_text, spec_stories_to_draft_dicts, SpecStory,
)


class TestEmptyOrNoHeaders:
    def test_empty_returns_empty(self):
        assert parse_spec_text("") == []
        assert parse_spec_text("   \n  \n") == []

    def test_no_story_headers_returns_empty(self):
        text = """# Product Requirements

## Overview
This is a PRD but has no story blocks.
Just prose.

## Requirements
Bullet list of things.
"""
        assert parse_spec_text(text) == []


class TestBasicHeaders:
    def test_single_story_header(self):
        text = "## Story: Add login endpoint\n\nUser can log in.\n"
        stories = parse_spec_text(text)
        assert len(stories) == 1
        assert stories[0].title == "Add login endpoint"
        assert "User can log in" in stories[0].body

    def test_feature_synonym(self):
        text = "## Feature: Something\n\nBody.\n"
        assert parse_spec_text(text)[0].title == "Something"

    def test_task_synonym(self):
        text = "## Task: Refactor cleanup\n\nBody.\n"
        assert parse_spec_text(text)[0].title == "Refactor cleanup"

    def test_case_insensitive_header(self):
        text = "## story: lower case\n\nBody.\n"
        assert parse_spec_text(text)[0].title == "lower case"


class TestMultipleStories:
    def test_three_stories(self):
        text = """## Story: First
body1

## Story: Second
body2

## Story: Third
body3
"""
        stories = parse_spec_text(text)
        assert [s.title for s in stories] == ["First", "Second", "Third"]


class TestFieldExtraction:
    def test_files_field(self):
        text = """## Story: Add auth
Body here.

Files: auth/routes.py, auth/tokens.py
"""
        s = parse_spec_text(text)[0]
        assert s.files_to_touch == ["auth/routes.py", "auth/tokens.py"]

    def test_priority_field(self):
        text = "## Story: X\nBody\n\nPriority: 90\n"
        assert parse_spec_text(text)[0].priority == 90

    def test_type_field(self):
        text = "## Story: X\nBody\n\nType: architecture\n"
        assert parse_spec_text(text)[0].type == "architecture"

    def test_invalid_type_falls_back_to_feature(self):
        text = "## Story: X\nBody\n\nType: nonsense\n"
        assert parse_spec_text(text)[0].type == "feature"

    def test_component_field(self):
        text = "## Story: X\nBody\n\nComponent: Auth\n"
        assert parse_spec_text(text)[0].component == "auth"

    def test_depends_field(self):
        text = "## Story: X\nBody\n\nDepends: 1, 3\n"
        assert parse_spec_text(text)[0].depends_on == [1, 3]


class TestAcceptanceCriteria:
    def test_ac_bullets(self):
        text = """## Story: Login
Body

AC:
  - Returns 200 on success
  - Returns 401 on bad password
  - Rate-limited to 10/min
"""
        s = parse_spec_text(text)[0]
        assert s.acceptance_criteria == [
            "Returns 200 on success",
            "Returns 401 on bad password",
            "Rate-limited to 10/min",
        ]

    def test_ac_ends_at_blank_line(self):
        text = """## Story: X
Body.

AC:
  - First
  - Second

Files: x.py
"""
        s = parse_spec_text(text)[0]
        assert s.acceptance_criteria == ["First", "Second"]
        assert s.files_to_touch == ["x.py"]

    def test_no_ac_block_empty_list(self):
        text = "## Story: X\nBody\n"
        assert parse_spec_text(text)[0].acceptance_criteria == []


class TestToDraftDicts:
    def test_deps_converted_to_zero_based_indices(self):
        # Depends: 2 means the second-listed story (1-based), which is index 1.
        text = """## Story: A
body

## Story: B
body

Depends: 1
"""
        dicts = spec_stories_to_draft_dicts(parse_spec_text(text))
        assert dicts[1]["depends_on"] == [0]

    def test_self_reference_dropped(self):
        text = """## Story: A
Depends: 1
"""
        dicts = spec_stories_to_draft_dicts(parse_spec_text(text))
        assert dicts[0]["depends_on"] == []

    def test_out_of_range_dropped(self):
        text = """## Story: A
Depends: 99, 100
"""
        dicts = spec_stories_to_draft_dicts(parse_spec_text(text))
        assert dicts[0]["depends_on"] == []

    def test_all_fields_flow_through(self):
        text = """## Story: Full example
This is the body.

Files: a/b.py, c/d.py
Component: alpha
Priority: 77
Type: architecture

AC:
  - one
  - two
"""
        d = spec_stories_to_draft_dicts(parse_spec_text(text))[0]
        assert d["title"] == "Full example"
        assert d["type"] == "architecture"
        assert d["priority"] == 77
        assert d["component"] == "alpha"
        assert d["files_to_touch"] == ["a/b.py", "c/d.py"]
        assert d["acceptance_criteria"] == ["one", "two"]
