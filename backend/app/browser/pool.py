from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.browser.session import BrowserSession


class BrowserPool:
    def __init__(self, max_sessions: int = 8):
        self.max_sessions = max_sessions
        self._active: dict[str, BrowserSession] = {}
        self._semaphore = asyncio.Semaphore(max_sessions)

    async def run_session(
        self,
        cluster_id: str,
        agent_profile: dict[str, Any],
        architect_outputs: dict[str, Any],
        url: str,
    ) -> dict[str, Any]:
        async with self._semaphore:
            session_id = f"{cluster_id}_{uuid.uuid4().hex[:8]}"
            session = BrowserSession(
                session_id=session_id,
                cluster_id=cluster_id,
                agent_profile=agent_profile,
                architect_outputs=architect_outputs,
            )
            self._active[session_id] = session
            try:
                return await session.run(url)
            finally:
                await session.close()
                self._active.pop(session_id, None)

    async def run_cluster_batch(
        self,
        cluster_id: str,
        agent_profiles: list[dict],
        architect_outputs: dict[str, Any],
        url: str,
    ) -> list[dict]:
        tasks = [
            self.run_session(cluster_id, profile, architect_outputs, url)
            for profile in agent_profiles
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[dict[str, Any]] = []
        for r in raw:
            if isinstance(r, Exception):
                results.append({
                    "converted": False,
                    "events": [{"action": "error", "reason": str(r)}],
                    "pages_visited": 1,
                    "duration_seconds": 0,
                    "action_count": 0,
                })
            else:
                results.append(r)
        return results

    @property
    def active_count(self) -> int:
        return len(self._active)


# Global singleton
browser_pool = BrowserPool(max_sessions=8)
