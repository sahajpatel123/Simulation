from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserSession:
    session_id: str
    cluster_id: str  # e.g. "metro_power_professional"
    agent_profile: dict[str, Any]
    architect_outputs: dict[str, Any]  # from Conductor cluster_results
    _browser: Any = field(default=None, repr=False)
    _context: Any = field(default=None, repr=False)
    _page: Any = field(default=None, repr=False)
    _pw: Any = field(default=None, repr=False)

    # Cluster-derived behavior
    @property
    def is_mobile(self) -> bool:
        device = self.agent_profile.get("device_primary", "desktop")
        return device == "mobile"

    @property
    def patience_score(self) -> float:
        return float(self.agent_profile.get("patience_score", 0.5))

    @property
    def max_actions(self) -> int:
        return max(5, int(self.patience_score * 30))

    async def initialize(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        viewport = {"width": 375, "height": 667} if self.is_mobile else {"width": 1280, "height": 720}
        ua = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
            if self.is_mobile
            else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self._context = await self._browser.new_context(viewport=viewport, user_agent=ua)
        self._page = await self._context.new_page()

        # Inject cluster context for JS access
        await self._page.add_init_script(
            f"""
            window.__thecee_cluster_id = {json.dumps(self.cluster_id)};
            window.__thecee_patience   = {self.patience_score};
            window.__thecee_mobile     = {str(self.is_mobile).lower()};
        """
        )

    async def run(self, url: str) -> dict[str, Any]:
        if not self._page:
            await self.initialize()

        start = time.time()
        events = []
        converted = False
        pages_visited = 1

        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            return self._result(events, False, pages_visited, time.time() - start, str(e))

        # Cluster-driven interaction loop
        trust = float(self.agent_profile.get("trust", 0.5))
        motivation = float(self.agent_profile.get("motivation", 0.5))
        price_s = float(self.agent_profile.get("price_sensitivity", 0.5))

        # Pricing architect override if available
        will_pay = float(
            self.architect_outputs.get("PricingArchitect", {})
            .get("metrics", {})
            .get("will_pay_probability", motivation * (1 - price_s))
        )
        brand_ok = float(
            self.architect_outputs.get("TrustArchitect", {})
            .get("metrics", {})
            .get("brand_deficit_multiplier", trust)
        )

        # Abandon immediately if trust too low
        if brand_ok < 0.30:
            events.append({"action": "abandon", "reason": "brand_deficit", "target": "ARRIVE"})
            return self._result(events, False, pages_visited, time.time() - start)

        for _ in range(self.max_actions):
            try:
                # Find next interactable thecee element
                elements = await self._page.query_selector_all("[data-thecee-id]")
                if not elements:
                    break

                el = random.choice(elements)
                thecee_id = await el.get_attribute("data-thecee-id")

                # Pricing gate
                if thecee_id in ["add-to-cart", "cta-primary", "checkout-form"]:
                    if random.random() > will_pay:
                        events.append({"action": "abandon", "reason": "price", "target": thecee_id})
                        break

                await el.scroll_into_view_if_needed()
                await el.click(timeout=3000)
                events.append({"action": "click", "target": thecee_id, "t": round(time.time() - start, 2)})

                # Detect conversion
                current_url = self._page.url
                if any(x in current_url.lower() for x in ["confirm", "success", "thank"]):
                    converted = True
                    events.append({"action": "converted", "target": thecee_id})
                    break

                # Patience-driven delay
                await asyncio.sleep(0.5 + (1 - self.patience_score) * 1.5)

            except Exception:
                break

        return self._result(events, converted, pages_visited, time.time() - start)

    def _result(self, events, converted, pages, duration, error=None) -> dict:
        return {
            "session_id": self.session_id,
            "cluster_id": self.cluster_id,
            "events": events,
            "converted": converted,
            "pages_visited": pages,
            "duration_seconds": round(duration, 2),
            "action_count": len(events),
            "error": error,
        }

    async def close(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
