"""TeamSupervisor — watches AsyncAgent tasks, restarts on crash with backoff."""

from __future__ import annotations

import asyncio
from typing import Any


DEFAULT_BACKOFFS = [5.0, 30.0, 300.0, 1800.0, 3600.0]  # 5s, 30s, 5m, 30m, 1h


class TeamSupervisor:
    def __init__(
        self,
        agents: dict[str, Any],
        emitter: Any,
        *,
        restart_backoffs: list[float] | None = None,
    ):
        self.agents = dict(agents)
        self.emitter = emitter
        self.restart_backoffs = list(restart_backoffs) if restart_backoffs \
            else list(DEFAULT_BACKOFFS)
        self._alive = True

    def stop(self) -> None:
        self._alive = False
        for a in self.agents.values():
            try:
                a.stop()
            except Exception:
                pass

    async def run(self) -> None:
        tasks: dict[str, asyncio.Task] = {}
        restart_counts: dict[str, int] = {name: 0 for name in self.agents}

        # Initial spawn
        for name, agent in self.agents.items():
            tasks[name] = asyncio.create_task(agent.loop(), name=name)

        while self._alive:
            if not tasks:
                break
            done, pending = await asyncio.wait(
                tasks.values(),
                timeout=0.5,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                name = t.get_name()
                exc = t.exception()
                if exc is not None:
                    self.emitter.emit(
                        "agent_crashed", role=name, error=str(exc)[:200],
                        summary=f"{name}: {type(exc).__name__}: {str(exc)[:120]}",
                    )
                    idx = min(restart_counts[name], len(self.restart_backoffs) - 1)
                    backoff = self.restart_backoffs[idx]
                    restart_counts[name] += 1
                    if self._alive:
                        await asyncio.sleep(backoff)
                        self.emitter.emit(
                            "agent_restarted", role=name,
                            attempt=restart_counts[name],
                            summary=f"{name} restarted (attempt #{restart_counts[name]})",
                        )
                        tasks[name] = asyncio.create_task(
                            self.agents[name].loop(), name=name,
                        )
                    else:
                        del tasks[name]
                else:
                    # Agent exited cleanly (probably via .stop())
                    del tasks[name]

        # Wait for all remaining agents to finish
        for t in tasks.values():
            try:
                await asyncio.wait_for(t, timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                t.cancel()
