from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.hardware.materials import estimate_component_cost, get_material, resolve_material_name


@dataclass
class BOMItem:
    component_id: str
    component_name: str
    material: str
    volume_cm3: float
    unit_cost_inr: float
    quantity: int
    total_cost_inr: float
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "component_name": self.component_name,
            "material": self.material,
            "volume_cm3": round(self.volume_cm3, 3),
            "unit_cost_inr": round(self.unit_cost_inr, 2),
            "quantity": self.quantity,
            "total_cost_inr": round(self.total_cost_inr, 2),
            "notes": self.notes,
        }


@dataclass
class CostEstimate:
    bom: list[BOMItem]
    bom_total_inr: float
    assembly_labour_inr: float
    tooling_cost_inr: float
    tooling_per_unit_inr: float
    landed_cost_inr: float
    target_price_inr: float
    margin_inr: float
    margin_pct: float
    break_even_moq: int
    moq: int
    verdict: str
    verdict_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "bom": [b.to_dict() for b in self.bom],
            "bom_total_inr": round(self.bom_total_inr, 2),
            "assembly_labour_inr": round(self.assembly_labour_inr, 2),
            "tooling_cost_inr": round(self.tooling_cost_inr, 2),
            "tooling_per_unit_inr": round(self.tooling_per_unit_inr, 2),
            "landed_cost_inr": round(self.landed_cost_inr, 2),
            "target_price_inr": round(self.target_price_inr, 2),
            "margin_inr": round(self.margin_inr, 2),
            "margin_pct": round(self.margin_pct, 2),
            "break_even_moq": self.break_even_moq,
            "moq": self.moq,
            "verdict": self.verdict,
            "verdict_reason": self.verdict_reason,
        }


class ManufacturingCostAnalyser:
    ASSEMBLY_LABOUR = {
        "simple": 80,
        "moderate": 180,
        "complex": 420,
    }

    TOOLING_COSTS = {
        "consumer_hardware": 250_000,
        "health_hardware": 400_000,
        "wearable": 350_000,
        "iot_hardware": 200_000,
        "b2b_hardware": 300_000,
    }

    FIXED_COMPONENT_COSTS = {
        "battery": 120,
        "pcb": 85,
        "screen": 350,
        "speaker": 45,
        "mic": 30,
        "sensor": 80,
        "motor": 95,
        "connector": 15,
    }

    def _tooling_category(self, spec: dict) -> str:
        raw = str(spec.get("category", "consumer_hardware") or "consumer_hardware")
        key = raw.strip().lower().replace(" ", "_").replace("-", "_")
        if key in self.TOOLING_COSTS:
            return key
        return "consumer_hardware"

    def generate_bom(self, spec: dict) -> list[BOMItem]:
        bom: list[BOMItem] = []
        for comp in spec.get("components", []):
            comp_id = str(comp.get("id", "unknown"))
            comp_name = str(comp.get("name", comp_id))
            mat_raw = str(comp.get("material", "ABS"))
            volume = float(comp.get("volume_cm3", 5.0))

            name_l = comp_name.lower()
            id_l = comp_id.lower()
            unit_cost = 0.0
            notes = ""
            matched = False
            for keyword, fixed_cost in self.FIXED_COMPONENT_COSTS.items():
                if keyword in name_l or keyword in id_l:
                    unit_cost = float(fixed_cost)
                    notes = f"Fixed cost estimate for {keyword}"
                    matched = True
                    break
            if not matched:
                unit_cost = float(estimate_component_cost(mat_raw, volume))
                mat_canonical = resolve_material_name(mat_raw)
                mat_spec = get_material(mat_canonical)
                notes = f"{mat_canonical} @ {mat_spec.cost_per_kg_inr} INR/kg"

            bom.append(
                BOMItem(
                    component_id=comp_id,
                    component_name=comp_name,
                    material=mat_raw,
                    volume_cm3=volume,
                    unit_cost_inr=round(unit_cost, 2),
                    quantity=1,
                    total_cost_inr=round(unit_cost, 2),
                    notes=notes,
                )
            )

        return bom

    def estimate(
        self,
        spec: dict,
        target_price_inr: float,
        moq: int = 500,
    ) -> CostEstimate:
        bom = self.generate_bom(spec)
        bom_total = sum(b.total_cost_inr for b in bom)

        complexity = str(spec.get("assembly_complexity", "moderate")).lower()
        labour = float(self.ASSEMBLY_LABOUR.get(complexity, 180))

        category = self._tooling_category(spec)
        tooling_total = float(self.TOOLING_COSTS.get(category, 250_000))
        tooling_unit = tooling_total / max(moq, 1)

        subtotal = bom_total + labour + tooling_unit
        logistics = subtotal * 0.15
        landed_cost = subtotal + logistics

        margin_inr = target_price_inr - landed_cost
        margin_pct = (
            (margin_inr / target_price_inr * 100) if target_price_inr > 0 else 0.0
        )

        cost_without_tooling = bom_total + labour + (bom_total + labour) * 0.15
        max_tooling_per_unit = target_price_inr * 0.40 - cost_without_tooling
        if max_tooling_per_unit > 0:
            break_even_moq = int(tooling_total / max_tooling_per_unit) + 1
        else:
            break_even_moq = 999_999

        verdict, verdict_reason = self.viability_verdict_from(
            margin_pct, break_even_moq, moq, landed_cost, target_price_inr
        )

        return CostEstimate(
            bom=bom,
            bom_total_inr=round(bom_total, 2),
            assembly_labour_inr=round(labour, 2),
            tooling_cost_inr=round(tooling_total, 2),
            tooling_per_unit_inr=round(tooling_unit, 2),
            landed_cost_inr=round(landed_cost, 2),
            target_price_inr=round(target_price_inr, 2),
            margin_inr=round(margin_inr, 2),
            margin_pct=round(margin_pct, 2),
            break_even_moq=break_even_moq,
            moq=moq,
            verdict=verdict,
            verdict_reason=verdict_reason,
        )

    def viability_verdict_from(
        self,
        margin_pct: float,
        break_even_moq: int,
        moq: int,
        landed_cost: float,
        target_price: float,
    ) -> tuple[str, str]:
        if target_price <= landed_cost:
            return (
                "NOT_VIABLE",
                (
                    f"Target price ₹{target_price:,.0f} is below landed cost "
                    f"₹{landed_cost:,.0f}. Product loses money at every unit."
                ),
            )
        if margin_pct < 20:
            return (
                "NOT_VIABLE",
                (
                    f"Margin {margin_pct:.1f}% is below 20% minimum. "
                    f"Insufficient buffer for returns, warranty, and marketing."
                ),
            )
        if break_even_moq > moq * 3:
            return (
                "NOT_VIABLE",
                (
                    f"Break-even requires {break_even_moq:,} units but MOQ is {moq:,}. "
                    f"Tooling cost unrecoverable at target volume."
                ),
            )
        if margin_pct < 35 or break_even_moq > moq * 1.5:
            return (
                "MARGINAL",
                (
                    f"Margin {margin_pct:.1f}% is acceptable but tight. "
                    f"Break-even at {break_even_moq:,} units — feasible with strong sales."
                ),
            )
        return (
            "VIABLE",
            (
                f"Margin {margin_pct:.1f}% is healthy. "
                f"Break-even at {break_even_moq:,} units within MOQ range."
            ),
        )

    def viability_verdict(self, cost_estimate: CostEstimate) -> str:
        return cost_estimate.verdict
