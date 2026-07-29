"""orgos.spawn.backends — pluggable execution backends.

The ``SpawnBackend`` ABC decouples governance (permission tiers, budgets,
audit) from *how* a role's brief is actually executed. Governance stays in
:func:`orgos.spawn.governance.spawn`; the backend just runs the LLM.

Ships:
  - :class:`SpawnBackend` — the ABC — and :class:`BackendResult`, its
    return contract.
  - :class:`AnthropicBackend` — official SDK, prompt caching, adaptive
    thinking, governed tool loop (the flagship).
  - :class:`LiteLLMBackend` — single-turn reference adapter, no tools.
The CrewAI engine (:mod:`orgos.spawn.governance.engine`) remains a separate
execution path that does not route through this ABC.
"""

from .anthropic_backend import AnthropicBackend
from .base import BackendResult, SpawnBackend
from .litellm_backend import LiteLLMBackend

__all__ = ["AnthropicBackend", "BackendResult", "SpawnBackend", "LiteLLMBackend"]
