"""Engine tests construct provider LLM objects (never call them) — supply
dummy keys so construction-time validation passes without real credentials."""

import os

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")
