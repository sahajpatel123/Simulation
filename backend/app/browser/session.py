from __future__ import annotations

import logging
logger = logging.getLogger(__name__)
import asyncio
import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.browser.agent_behaviour import AgentBehaviour


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

        behaviour = AgentBehaviour(
            cluster_id=self.cluster_id,
            agent_profile=self.agent_profile,
            architect_outputs=self.architect_outputs,
        )

        if not behaviour.trust_gate():
            events.append({"action": "abandon", "reason": "trust_gate", "target": "ARRIVE"})
            return self._result(events, False, pages_visited, time.time() - start)

        async def page_price_visible() -> bool:
            try:
                if await self._page.locator('[data-thecee-id="price"], .price, [itemprop="price"]').count() > 0:
                    return True
                body = await self._page.inner_text("body", timeout=3000)
                return "₹" in body or "$" in body or bool(
                    re.search(r"\d{3,}\s*(?:INR|rs\.?)", body, re.I)
                )
            except Exception:
                return False

        async def guess_cart_price() -> float:
            for sel in ('[data-thecee-id="price"]', "[data-price]", ".price"):
                try:
                    loc = self._page.locator(sel)
                    if await loc.count() == 0:
                        continue
                    txt = await loc.first.inner_text(timeout=500)
                    m = re.search(r"[\d,]+(?:\.\d+)?", txt.replace(",", "").replace("₹", "").strip())
                    if m:
                        return float(m.group(0).replace(",", ""))
                except Exception:
                    continue
            return 999.0

        for _ in range(self.max_actions):
            try:
                # Find next interactable thecee element
                elements = await self._page.query_selector_all("[data-thecee-id]")
                if not elements:
                    break

                el = random.choice(elements)
                thecee_id = await el.get_attribute("data-thecee-id") or ""

                if thecee_id == "checkout-form":
                    field_count = await self._page.locator("input, select, textarea").count()
                    if behaviour.should_abandon_form(field_count):
                        events.append(
                            {"action": "abandon", "reason": "form_friction", "target": thecee_id}
                        )
                        break

                elif thecee_id == "add-to-cart":
                    price_guess = await guess_cart_price()
                    if not behaviour.should_add_to_cart(price_guess):
                        events.append({"action": "abandon", "reason": "price", "target": thecee_id})
                        break

                elif thecee_id == "cta-primary":
                    pv = await page_price_visible()
                    if not behaviour.should_click_cta(price_visible=pv):
                        events.append(
                            {"action": "abandon", "reason": "cta_decline", "target": thecee_id}
                        )
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

                await asyncio.sleep(behaviour.get_interaction_delay())

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
        except Exception as _exc:
            logger.debug(
                "%s suppressed: %s",
                __name__,
                _exc,
            )
