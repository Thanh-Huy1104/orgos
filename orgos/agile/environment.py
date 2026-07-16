"""Repo environment detection — inform workers what runtime/tests to expect.

Not authoritative, but a strong hint. We surface this in worker briefs so a
Node project doesn't get `pytest` suggestions and a Rust project doesn't get
`pip install`.

Detection is done by looking at marker files at the repo root:

    Python  → requirements.txt, pyproject.toml, setup.py, Pipfile
    Node    → package.json
    Go      → go.mod
    Rust    → Cargo.toml
    Ruby    → Gemfile
    Java    → pom.xml, build.gradle
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RepoEnvironment:
    language: str          # "python" | "node" | "go" | "rust" | "ruby" | "java" | "unknown"
    package_manager: str   # "pip" | "poetry" | "npm" | "yarn" | "pnpm" | "go" | "cargo" | "bundler" | "maven" | "gradle" | "unknown"
    install_cmd: str       # command to install deps ("" if none/unknown)
    test_cmd: str          # default test command hint
    lint_cmd: str          # optional lint hint (may be empty)
    markers_found: list[str]  # marker filenames actually present at root


_DETECTORS = [
    # (language, package_manager, marker files (any of), install_cmd, test_cmd, lint_cmd)
    ("python", "poetry",  ["poetry.lock"],           "poetry install",                            "poetry run pytest -q",  ""),
    ("python", "pipenv",  ["Pipfile.lock", "Pipfile"], "pipenv install --dev",                    "pipenv run pytest -q",  ""),
    ("python", "pip",     ["requirements-dev.txt"],  "pip install -r requirements-dev.txt",       "pytest -q",             ""),
    ("python", "pip",     ["requirements.txt"],      "pip install -r requirements.txt",           "pytest -q",             ""),
    ("python", "pip",     ["pyproject.toml"],        "pip install -e '.[dev]' || pip install -e .","pytest -q",            ""),
    ("python", "pip",     ["setup.py"],              "pip install -e .",                          "pytest -q",             ""),
    ("node",   "pnpm",    ["pnpm-lock.yaml"],        "pnpm install",                              "pnpm test",             ""),
    ("node",   "yarn",    ["yarn.lock"],             "yarn install",                              "yarn test",             ""),
    ("node",   "npm",     ["package-lock.json", "package.json"], "npm install",                   "npm test",              ""),
    ("go",     "go",      ["go.mod"],                "go mod download",                           "go test ./...",         "go vet ./..."),
    ("rust",   "cargo",   ["Cargo.toml"],            "cargo fetch",                               "cargo test",            "cargo clippy"),
    ("ruby",   "bundler", ["Gemfile"],               "bundle install",                            "bundle exec rspec",     ""),
    ("java",   "maven",   ["pom.xml"],               "mvn install -DskipTests",                   "mvn test",              ""),
    ("java",   "gradle",  ["build.gradle", "build.gradle.kts"], "./gradlew build -x test",        "./gradlew test",        ""),
]


def detect_environment(repo_root: Path) -> RepoEnvironment:
    """Detect repo environment. Falls back to `unknown` if no markers found."""
    root = Path(repo_root)
    for language, pm, markers, install, test, lint in _DETECTORS:
        found = [m for m in markers if (root / m).exists()]
        if found:
            return RepoEnvironment(
                language=language,
                package_manager=pm,
                install_cmd=install,
                test_cmd=test,
                lint_cmd=lint,
                markers_found=found,
            )
    return RepoEnvironment(
        language="unknown",
        package_manager="unknown",
        install_cmd="",
        test_cmd="",
        lint_cmd="",
        markers_found=[],
    )


def environment_hint_for_brief(env: RepoEnvironment) -> str:
    """Render a short 'environment hint' block for a worker brief."""
    if env.language == "unknown":
        return (
            "REPO ENVIRONMENT: unknown (no standard marker files found).\n"
            "  Assume Python + pytest unless the story body says otherwise.\n"
        )
    return (
        f"REPO ENVIRONMENT:\n"
        f"  language:    {env.language}\n"
        f"  package mgr: {env.package_manager}\n"
        f"  install:     {env.install_cmd or '(none needed)'}\n"
        f"  test:        {env.test_cmd or '(no default)'}\n"
        + (f"  lint:        {env.lint_cmd}\n" if env.lint_cmd else "")
        + f"  markers:     {env.markers_found}\n"
    )
