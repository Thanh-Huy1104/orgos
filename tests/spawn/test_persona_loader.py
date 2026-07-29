"""Tests for the persona file loader (Plan 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from orgos.spawn.governance.contracts import PermissionTier, RoleSpec
from orgos.spawn.governance.persona_loader import (
    PersonaFile,
    assemble_system_prompt,
    load_agent,
    load_layer,
    load_persona_file,
)
from orgos.spawn.governance.persona_schema import (
    FILE_TYPES,
    REQUIRED_SECTIONS,
    PersonaValidationError,
    SimpleFrontmatter,
    SoulFrontmatter,
)

FIXTURES = Path(__file__).parent / "fixtures" / "agents"


class TestSchemaConstants:
    def test_file_types_are_the_five_expected(self):
        assert FILE_TYPES == ("soul", "brain", "habits", "memory", "heartbeat")

    def test_required_sections_covers_every_file_type_plus_principles(self):
        assert set(REQUIRED_SECTIONS.keys()) == {
            "principles", "soul", "brain", "habits", "memory", "heartbeat",
        }


class TestSoulFrontmatter:
    def test_minimal_valid_soul(self):
        fm = SoulFrontmatter(
            version="1.0.0",
            layer="specific",
            agent_name="architect",
            tier="worker",
        )
        assert fm.agent_name == "architect"
        assert fm.tier == "worker"
        assert fm.is_worker is False  # default
        assert fm.max_iter == 20  # default

    def test_soul_rejects_unknown_tier(self):
        with pytest.raises(ValidationError):
            SoulFrontmatter(
                version="1.0.0", layer="specific",
                agent_name="x", tier="janitor",
            )

    def test_soul_rejects_unknown_layer(self):
        with pytest.raises(ValidationError):
            SoulFrontmatter(
                version="1.0.0", layer="astral",
                agent_name="x", tier="worker",
            )


class TestPersonaValidationError:
    def test_is_valueerror_subclass(self):
        assert issubclass(PersonaValidationError, ValueError)


class TestLoadPersonaFile:
    def test_loads_a_valid_soul_file(self):
        pf = load_persona_file(FIXTURES / "sample_worker" / "soul.md", "soul")
        assert isinstance(pf, PersonaFile)
        assert pf.file_type == "soul"
        assert pf.frontmatter.agent_name == "sample_worker"
        assert pf.frontmatter.tier == "worker"
        assert pf.frontmatter.is_worker is True
        assert "## Identity" in pf.body

    def test_loads_a_valid_principles_file(self):
        pf = load_persona_file(
            FIXTURES / "_principles" / "principles.md", "principles",
        )
        assert pf.file_type == "principles"
        assert pf.frontmatter.layer == "principles"
        assert "## Delivery Philosophy" in pf.body

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(PersonaValidationError, match="not found"):
            load_persona_file(tmp_path / "nope.md", "soul")

    def test_missing_frontmatter_raises(self, tmp_path):
        p = tmp_path / "bad.md"
        p.write_text("no frontmatter here\n## Identity\nx\n")
        with pytest.raises(PersonaValidationError, match="frontmatter"):
            load_persona_file(p, "soul")

    def test_bad_frontmatter_field_raises(self, tmp_path):
        p = tmp_path / "bad.md"
        p.write_text(
            "---\nversion: 1.0.0\nlayer: specific\nagent_name: x\n"
            "tier: janitor\n---\n## Identity\nx\n"
        )
        with pytest.raises(PersonaValidationError):
            load_persona_file(p, "soul")

    def test_missing_body_section_warns_but_loads(self, tmp_path, caplog):
        p = tmp_path / "soul.md"
        p.write_text(
            "---\nversion: 1.0.0\nlayer: specific\n"
            "agent_name: x\ntier: worker\n---\n"
            "## Identity\nx\n"  # missing Values / Stance / Optimizes For
        )
        pf = load_persona_file(p, "soul")
        assert pf is not None
        assert any("missing section" in r.message.lower() for r in caplog.records)

    def test_split_frontmatter_handles_crlf(self, tmp_path):
        p = tmp_path / "crlf.md"
        p.write_bytes(b"---\r\nversion: 1.0.0\r\nlayer: specific\r\nagent_name: x\r\ntier: worker\r\n---\r\n## Identity\r\nx\r\n")
        pf = load_persona_file(p, "soul")
        assert pf.frontmatter.version == "1.0.0"  # would fail with "1.0.0\r" pre-fix
        assert pf.frontmatter.agent_name == "x"


class TestLoadLayer:
    def test_loads_all_five_files_for_specific_layer(self):
        layer = load_layer(FIXTURES / "sample_worker", FILE_TYPES)
        assert set(layer.keys()) == set(FILE_TYPES)
        assert layer["soul"].frontmatter.agent_name == "sample_worker"

    def test_loads_worker_base_layer(self):
        layer = load_layer(FIXTURES / "_worker_base", FILE_TYPES)
        assert set(layer.keys()) == set(FILE_TYPES)
        assert layer["soul"].frontmatter.layer == "worker_base"

    def test_missing_file_in_layer_raises(self, tmp_path):
        d = tmp_path / "incomplete_agent"
        d.mkdir()
        (d / "soul.md").write_text(
            "---\nversion: 1.0.0\nlayer: specific\n"
            "agent_name: x\ntier: worker\n---\n## Identity\nx\n"
        )
        # brain / habits / memory / heartbeat missing
        with pytest.raises(PersonaValidationError, match="brain.md"):
            load_layer(d, FILE_TYPES)


class TestAssembleSystemPrompt:
    def test_orders_layers_principles_then_worker_then_specific(self):
        principles = load_persona_file(
            FIXTURES / "_principles" / "principles.md", "principles",
        )
        worker_base = load_layer(FIXTURES / "_worker_base", FILE_TYPES)
        specific = load_layer(FIXTURES / "sample_worker", FILE_TYPES)

        prompt = assemble_system_prompt(principles, worker_base, specific)

        # principles come first
        assert prompt.index("=== LAYER: PRINCIPLES ===") < prompt.index(
            "=== LAYER: WORKER_BASE ==="
        )
        assert prompt.index("=== LAYER: WORKER_BASE ===") < prompt.index(
            "=== LAYER: SPECIFIC ==="
        )
        # heartbeat is last within specific → falls at the end of the prompt
        assert prompt.rstrip().endswith(specific["heartbeat"].body.rstrip())

    def test_skips_worker_base_when_not_a_worker(self):
        principles = load_persona_file(
            FIXTURES / "_principles" / "principles.md", "principles",
        )
        specific = load_layer(FIXTURES / "sample_po", FILE_TYPES)
        prompt = assemble_system_prompt(principles, None, specific)
        assert "=== LAYER: WORKER_BASE ===" not in prompt


class TestLoadAgent:
    def test_loads_a_worker_agent_end_to_end(self):
        role = load_agent(FIXTURES, "sample_worker")
        assert isinstance(role, RoleSpec)
        assert role.name == "sample_worker"
        assert role.tier == PermissionTier.WORKER
        assert role.max_iter == 8
        assert "=== LAYER: WORKER_BASE ===" in role.system_prompt
        assert role.success_criteria == [
            "Produces a valid HandoffEnvelope.",
            "Diff <= 400 LOC.",
        ]

    def test_loads_a_non_worker_agent_and_skips_worker_base(self):
        role = load_agent(FIXTURES, "sample_po")
        assert role.tier == PermissionTier.ORCHESTRATOR
        assert "=== LAYER: WORKER_BASE ===" not in role.system_prompt

    def test_from_agent_dir_classmethod_delegates(self):
        role = RoleSpec.from_agent_dir(FIXTURES, "sample_worker")
        assert role.name == "sample_worker"

    def test_load_agent_rejects_underscore_agent_name(self):
        with pytest.raises(PersonaValidationError, match="reserved"):
            load_agent(FIXTURES, "_worker_base")


class TestGolden:
    """Snapshot the exact shape of an assembled worker RoleSpec so future
    changes to layer ordering, section headers, or field mapping surface as
    test failures rather than silently drifting the boot prompt."""

    def test_worker_role_shape_is_stable(self):
        role = RoleSpec.from_agent_dir(FIXTURES, "sample_worker")

        # Field mapping.
        assert role.name == "sample_worker"
        assert role.tier == PermissionTier.WORKER
        assert role.max_iter == 8
        assert role.description == "Sample delivery worker used in unit tests."
        assert role.model is None

        # Prompt structure (attention ordering matters, per spec §0.1).
        p = role.system_prompt
        i_principles = p.index("=== LAYER: PRINCIPLES ===")
        i_worker = p.index("=== LAYER: WORKER_BASE ===")
        i_specific = p.index("=== LAYER: SPECIFIC ===")
        assert i_principles < i_worker < i_specific

        # HEARTBEAT is the last section rendered inside the SPECIFIC layer.
        specific_block = p[i_specific:]
        assert specific_block.index("--- SOUL ---") < specific_block.index(
            "--- HEARTBEAT ---"
        )
        assert (
            specific_block.rindex("--- HEARTBEAT ---")
            == specific_block.rindex("--- ")
        ), "HEARTBEAT must be the last '--- X ---' section in the SPECIFIC block"
