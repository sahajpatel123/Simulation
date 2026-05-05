from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.hardware.materials import get_material, resolve_material_name
from app.hardware.test_configs import TestConfig


@dataclass
class TestResult:
    test_type: str
    status: str  # PASS | FAIL | PARTIAL
    pass_rate: float  # 0.0-1.0
    failed_components: list[str]
    failure_points: list[dict]
    metrics: dict
    recommendations: list[str]
    severity: str  # CRITICAL | WARNING | INFO

    def to_dict(self) -> dict:
        return {
            "test_type": self.test_type,
            "status": self.status,
            "pass_rate": round(self.pass_rate, 4),
            "failed_components": self.failed_components,
            "failure_points": self.failure_points,
            "metrics": self.metrics,
            "recommendations": self.recommendations,
            "severity": self.severity,
        }


class PhysicsSimulationEngine:
    _FALLBACK = {
        "tensile_strength_mpa": 40.0,
        "density_g_cm3": 1.05,
        "thermal_limit_celsius": 80.0,
        "water_resistance_ip_rating": "IP00",
    }

    def _get_mat(self, raw_name: str) -> Any:
        canonical = resolve_material_name(raw_name)
        return get_material(canonical)

    def _mat_val(self, mat: Any, key: str) -> float:
        if mat and hasattr(mat, key):
            return float(getattr(mat, key))
        return float(self._FALLBACK.get(key, 0.0))

    def simulate_drop(self, spec: dict, config: TestConfig) -> TestResult:
        height_m = config.parameters.get("height_cm", 100) / 100.0
        repetitions = config.parameters.get("repetitions", 3)
        surface = config.parameters.get("surface_type", "concrete")
        mass_kg = spec.get("dimensions", {}).get("weight_grams", 200) / 1000.0

        g = 9.81
        velocity = math.sqrt(2 * g * height_m)
        contact_time = 0.005 if surface == "concrete" else 0.015
        impact_force_n = mass_kg * velocity / contact_time

        failed_components: list[str] = []
        failure_points: list[dict] = []
        component_results: list[bool] = []

        for comp in spec.get("components", []):
            mat = self._get_mat(comp.get("material", "ABS"))
            tensile = self._mat_val(mat, "tensile_strength_mpa")
            volume_cm3 = float(comp.get("volume_cm3", 5.0))
            area_cm2 = max(1.0, volume_cm3 ** (2 / 3))
            area_m2 = area_cm2 / 10000.0
            stress_mpa = (impact_force_n / area_m2) / 1_000_000

            stress_rating = float(comp.get("stress_rating", 0.5))
            effective_stress = stress_mpa * (0.5 + stress_rating)

            fatigue_factor = 1.0 + (repetitions - 1) * 0.15
            final_stress = effective_stress * fatigue_factor

            passed = final_stress < tensile * 0.8
            component_results.append(passed)

            if not passed:
                failed_components.append(comp["id"])
                failure_points.append(
                    {
                        "component_id": comp["id"],
                        "reason": (
                            f"Stress {final_stress:.1f} MPa exceeds {tensile * 0.8:.1f} MPa limit"
                        ),
                        "severity": "CRITICAL" if final_stress > tensile else "WARNING",
                    }
                )

        pass_rate = sum(component_results) / max(len(component_results), 1)
        status = (
            "PASS"
            if not failed_components
            else ("PARTIAL" if pass_rate > 0.5 else "FAIL")
        )
        severity = (
            "CRITICAL"
            if status == "FAIL"
            else ("WARNING" if status == "PARTIAL" else "INFO")
        )

        recs: list[str] = []
        if failed_components:
            recs.append(f"Reinforce {failed_components[0]} with higher tensile material")
            recs.append("Add rubber bumpers or protective casing")
        if repetitions > 1 and status != "PASS":
            recs.append("Consider shock-absorbing internal mounts")

        return TestResult(
            test_type="DROP_TEST",
            status=status,
            pass_rate=round(pass_rate, 4),
            failed_components=failed_components,
            failure_points=failure_points,
            metrics={
                "impact_force_n": round(impact_force_n, 2),
                "velocity_ms": round(velocity, 3),
                "height_m": height_m,
                "mass_kg": mass_kg,
                "repetitions": repetitions,
                "surface": surface,
            },
            recommendations=recs,
            severity=severity,
        )

    def simulate_thermal(self, spec: dict, config: TestConfig) -> TestResult:
        min_c = config.parameters.get("min_celsius", -10)
        max_c = config.parameters.get("max_celsius", 60)
        cycles = config.parameters.get("cycles", 50)
        delta = max_c - min_c

        failed_components: list[str] = []
        failure_points: list[dict] = []
        component_results: list[bool] = []

        for comp in spec.get("components", []):
            mat = self._get_mat(comp.get("material", "ABS"))
            thermal_lim = self._mat_val(mat, "thermal_limit_celsius")

            limit_exceeded = max_c > thermal_lim

            mat_lower = comp.get("material", "").lower()
            name_lower = comp.get("name", "").lower()
            is_pcb = "pcb" in mat_lower or "electronic" in name_lower
            solder_fatigue = (delta / 100.0) * (cycles / 50.0) if is_pcb else 0.0

            is_seal = "rubber" in mat_lower or "seal" in name_lower
            seal_degrade = min(1.0, cycles / 200.0) if is_seal else 0.0

            fail = limit_exceeded or solder_fatigue > 0.80 or seal_degrade > 0.70
            component_results.append(not fail)

            if fail:
                reason = (
                    f"Temperature {max_c}C exceeds material limit {thermal_lim}C"
                    if limit_exceeded
                    else (
                        f"Solder fatigue index {solder_fatigue:.2f} after {cycles} cycles"
                        if solder_fatigue > 0.80
                        else f"Seal degradation {seal_degrade * 100:.0f}% after {cycles} cycles"
                    )
                )
                failed_components.append(comp["id"])
                failure_points.append(
                    {
                        "component_id": comp["id"],
                        "reason": reason,
                        "severity": "CRITICAL" if limit_exceeded else "WARNING",
                    }
                )

        pass_rate = sum(component_results) / max(len(component_results), 1)
        status = (
            "PASS"
            if not failed_components
            else ("PARTIAL" if pass_rate > 0.5 else "FAIL")
        )

        recs: list[str] = []
        if any("limit" in fp["reason"] for fp in failure_points):
            recs.append("Use higher thermal limit material for critical components")
        if any("solder" in fp["reason"] for fp in failure_points):
            recs.append("Add thermal relief on PCB copper pours")
        if any("seal" in fp["reason"] for fp in failure_points):
            recs.append(
                "Replace rubber seals with silicone rated to wider temperature range"
            )

        return TestResult(
            test_type="THERMAL_CYCLE",
            status=status,
            pass_rate=round(pass_rate, 4),
            failed_components=failed_components,
            failure_points=failure_points,
            metrics={
                "delta_celsius": delta,
                "cycles": cycles,
                "min_celsius": min_c,
                "max_celsius": max_c,
            },
            recommendations=recs,
            severity=(
                "CRITICAL"
                if status == "FAIL"
                else ("WARNING" if status == "PARTIAL" else "INFO")
            ),
        )

    def simulate_water_ingress(self, spec: dict, config: TestConfig) -> TestResult:
        target_ip = config.parameters.get("ip_rating_target", "IP54")
        duration = config.parameters.get("duration_minutes", 30)
        pressure = config.parameters.get("pressure_bar", 0)

        IP_SCORES = {
            "IP00": 0,
            "IP44": 4,
            "IP54": 5,
            "IP65": 7,
            "IP67": 9,
            "IP68": 10,
        }
        target_score = IP_SCORES.get(target_ip, 5)

        has_rubber_seal = any(
            "rubber" in c.get("material", "").lower()
            or "silicone" in c.get("material", "").lower()
            for c in spec.get("components", [])
        )
        has_metal_shell = any(
            "aluminium" in c.get("material", "").lower()
            or "steel" in c.get("material", "").lower()
            for c in spec.get("components", [])
        )
        gap_count = max(1, len(spec.get("components", [])) - 2)

        achieved_score = 3.0
        if has_rubber_seal:
            achieved_score += 3
        if has_metal_shell:
            achieved_score += 2
        achieved_score -= min(3.0, gap_count * 0.5)
        achieved_score = max(0.0, min(10.0, achieved_score))

        passed = achieved_score >= target_score
        gap_penalty = max(0.0, (target_score - achieved_score) / max(target_score, 1))
        pass_rate = max(0.0, 1.0 - gap_penalty)

        failed_components: list[str] = []
        failure_points: list[dict] = []
        if not passed:
            for comp in spec.get("components", []):
                if any(z in comp.get("zone", "") for z in ["shell", "top", "bottom"]):
                    failed_components.append(comp["id"])
                    failure_points.append(
                        {
                            "component_id": comp["id"],
                            "reason": (
                                f"Insufficient sealing for {target_ip} — "
                                f"achieved ~IP{int(achieved_score * 7)}"
                            ),
                            "severity": "CRITICAL",
                        }
                    )
                    if len(failed_components) >= 2:
                        break

        recs: list[str] = []
        if not passed:
            if not has_rubber_seal:
                recs.append(f"Add silicone O-ring seals to achieve {target_ip}")
            if gap_count > 3:
                recs.append("Reduce component gaps — use unified shell design")
            if pressure > 0:
                recs.append("Pressure-rated seals required for submersion depth")

        return TestResult(
            test_type="WATER_INGRESS",
            status="PASS" if passed else "FAIL",
            pass_rate=round(pass_rate, 4),
            failed_components=failed_components,
            failure_points=failure_points,
            metrics={
                "target_ip": target_ip,
                "achieved_score": round(achieved_score, 2),
                "target_score": target_score,
                "duration_min": duration,
                "has_seal": has_rubber_seal,
            },
            recommendations=recs,
            severity="CRITICAL" if not passed else "INFO",
        )

    def simulate_battery(self, spec: dict, config: TestConfig) -> TestResult:
        load_profile = config.parameters.get("load_profile", "mixed")
        ambient_temp = config.parameters.get("ambient_temp", 25)
        target_hours = config.parameters.get("target_runtime_hours", 8)

        capacity_mah = config.parameters.get("capacity_mah", 0)
        if capacity_mah == 0:
            for comp in spec.get("components", []):
                if "battery" in comp.get("name", "").lower():
                    capacity_mah = float(comp.get("volume_cm3", 5)) * 200
                    break
        if capacity_mah == 0:
            capacity_mah = 1000

        LOAD_MA = {
            "idle": 5,
            "light": 30,
            "mixed": 80,
            "heavy": 150,
            "peak": 300,
        }
        draw_ma = LOAD_MA.get(load_profile, 80)

        if ambient_temp > 40:
            temp_factor = 0.80
        elif ambient_temp < 0:
            temp_factor = 0.75
        else:
            temp_factor = 1.00

        effective_capacity = capacity_mah * temp_factor
        runtime_hours = effective_capacity / max(draw_ma, 1)
        collapse_hours = (effective_capacity * 0.10) / max(draw_ma, 1)
        passes_target = runtime_hours >= target_hours

        recs: list[str] = []
        if not passes_target:
            needed_mah = int(draw_ma * target_hours / temp_factor)
            recs.append(f"Increase battery to ~{needed_mah}mAh for {target_hours}h target")
            recs.append(f"Optimise {load_profile} power draw — target < {int(draw_ma * 0.7)}mA")
        if ambient_temp > 40:
            recs.append("Add thermal management for high-temp battery derating")

        return TestResult(
            test_type="BATTERY_DRAIN",
            status="PASS" if passes_target else "FAIL",
            pass_rate=min(1.0, round(runtime_hours / max(target_hours, 1), 4)),
            failed_components=[],
            failure_points=(
                []
                if passes_target
                else [
                    {
                        "component_id": "battery",
                        "reason": (
                            f"Runtime {runtime_hours:.1f}h below target {target_hours}h"
                        ),
                        "severity": "CRITICAL",
                    }
                ]
            ),
            metrics={
                "capacity_mah": capacity_mah,
                "load_profile": load_profile,
                "draw_ma": draw_ma,
                "runtime_hours": round(runtime_hours, 2),
                "collapse_hours": round(collapse_hours, 2),
                "temp_factor": temp_factor,
                "target_hours": target_hours,
            },
            recommendations=recs,
            severity="CRITICAL" if not passes_target else "INFO",
        )

    def simulate_vibration(self, spec: dict, config: TestConfig) -> TestResult:
        freq_hz = config.parameters.get("frequency_hz", 20)
        amplitude = config.parameters.get("amplitude_mm", 0.5)
        duration = config.parameters.get("duration_min", 60)

        failed_components: list[str] = []
        failure_points: list[dict] = []
        component_results: list[bool] = []
        mass_kg = spec.get("dimensions", {}).get("weight_grams", 200) / 1000.0

        for comp in spec.get("components", []):
            mat = self._get_mat(comp.get("material", "ABS"))
            tensile = self._mat_val(mat, "tensile_strength_mpa")
            volume_cm3 = float(comp.get("volume_cm3", 5.0))

            angular_freq = 2 * math.pi * freq_hz
            force_n = mass_kg * (angular_freq**2) * (amplitude / 1000)
            area_m2 = max(0.0001, (volume_cm3 ** (2 / 3)) / 10000)
            stress_mpa = (force_n / area_m2) / 1_000_000

            cycles = duration * freq_hz * 60
            fatigue_reduction = max(0.5, 1.0 - (cycles / 10_000_000) * 0.3)
            effective_tensile = tensile * fatigue_reduction

            passed = stress_mpa < effective_tensile * 0.6
            component_results.append(passed)
            if not passed:
                failed_components.append(comp["id"])
                failure_points.append(
                    {
                        "component_id": comp["id"],
                        "reason": (
                            f"Vibration fatigue stress {stress_mpa:.2f} MPa over "
                            f"{cycles:,.0f} cycles"
                        ),
                        "severity": "WARNING",
                    }
                )

        pass_rate = sum(component_results) / max(len(component_results), 1)
        status = (
            "PASS"
            if not failed_components
            else ("PARTIAL" if pass_rate > 0.5 else "FAIL")
        )

        recs: list[str] = []
        if failed_components:
            recs.append("Add vibration dampening mounts for sensitive components")
            recs.append(f"Avoid resonance frequencies near {freq_hz}Hz in enclosure design")

        return TestResult(
            test_type="VIBRATION",
            status=status,
            pass_rate=round(pass_rate, 4),
            failed_components=failed_components,
            failure_points=failure_points,
            metrics={
                "frequency_hz": freq_hz,
                "amplitude_mm": amplitude,
                "duration_min": duration,
                "fatigue_cycles": int(duration * freq_hz * 60),
            },
            recommendations=recs,
            severity=(
                "CRITICAL"
                if status == "FAIL"
                else ("WARNING" if status == "PARTIAL" else "INFO")
            ),
        )

    def simulate_compression(self, spec: dict, config: TestConfig) -> TestResult:
        force_kg = config.parameters.get("force_kg", 50)
        area_cm2 = config.parameters.get("contact_area_cm2", 10)
        duration_s = config.parameters.get("duration_seconds", 30)
        force_n = force_kg * 9.81
        stress_mpa = (force_n / (area_cm2 / 10000)) / 1_000_000

        failed_components: list[str] = []
        failure_points: list[dict] = []
        component_results: list[bool] = []

        for comp in spec.get("components", []):
            if comp.get("zone", "") not in ["top", "shell", "core"]:
                component_results.append(True)
                continue
            mat = self._get_mat(comp.get("material", "ABS"))
            tensile = self._mat_val(mat, "tensile_strength_mpa")
            passed = stress_mpa < tensile * 0.7
            component_results.append(passed)
            if not passed:
                failed_components.append(comp["id"])
                failure_points.append(
                    {
                        "component_id": comp["id"],
                        "reason": (
                            f"Compressive stress {stress_mpa:.2f} MPa exceeds "
                            f"{tensile * 0.7:.2f} MPa limit"
                        ),
                        "severity": "CRITICAL",
                    }
                )

        pass_rate = sum(component_results) / max(len(component_results), 1)
        status = (
            "PASS"
            if not failed_components
            else ("PARTIAL" if pass_rate > 0.5 else "FAIL")
        )

        return TestResult(
            test_type="COMPRESSION",
            status=status,
            pass_rate=round(pass_rate, 4),
            failed_components=failed_components,
            failure_points=failure_points,
            metrics={
                "force_kg": force_kg,
                "stress_mpa": round(stress_mpa, 4),
                "area_cm2": area_cm2,
                "duration_s": duration_s,
            },
            recommendations=(
                ["Increase wall thickness on load-bearing zones"]
                if failed_components
                else []
            ),
            severity=(
                "CRITICAL"
                if status == "FAIL"
                else ("WARNING" if status == "PARTIAL" else "INFO")
            ),
        )

    def simulate_uv_exposure(self, spec: dict, config: TestConfig) -> TestResult:
        hours = config.parameters.get("hours", 500)
        intensity = config.parameters.get("intensity", "standard")
        MULTIPLIER = {"low": 0.5, "standard": 1.0, "accelerated": 3.0}
        eff_hours = hours * MULTIPLIER.get(intensity, 1.0)

        failed_components: list[str] = []
        failure_points: list[dict] = []
        component_results: list[bool] = []

        SEAL_DEGRADE_HOURS = 800
        PLASTIC_DEGRADE_HOURS = 1500

        for comp in spec.get("components", []):
            mat_name = comp.get("material", "ABS").lower()
            is_plastic = any(p in mat_name for p in ["abs", "pp", "pc", "petg", "nylon"])
            is_seal = "rubber" in mat_name or "silicone" in mat_name
            is_metal = any(
                m in mat_name for m in ["aluminium", "steel", "copper", "titanium"]
            )

            if is_metal:
                component_results.append(True)
                continue

            if is_plastic and eff_hours > PLASTIC_DEGRADE_HOURS:
                failed_components.append(comp["id"])
                failure_points.append(
                    {
                        "component_id": comp["id"],
                        "reason": f"Plastic degradation after {eff_hours:.0f} effective UV hours",
                        "severity": "WARNING",
                    }
                )
                component_results.append(False)
            elif is_seal and eff_hours > SEAL_DEGRADE_HOURS:
                failed_components.append(comp["id"])
                failure_points.append(
                    {
                        "component_id": comp["id"],
                        "reason": f"Seal embrittlement after {eff_hours:.0f} effective UV hours",
                        "severity": "WARNING",
                    }
                )
                component_results.append(False)
            else:
                component_results.append(True)

        pass_rate = sum(component_results) / max(len(component_results), 1)
        status = (
            "PASS"
            if not failed_components
            else ("PARTIAL" if pass_rate > 0.5 else "FAIL")
        )

        recs: list[str] = []
        if failed_components:
            recs.append("Add UV stabiliser to plastic components")
            recs.append(
                "Use UV-resistant polycarbonate (PC) instead of ABS for outer shell"
            )

        return TestResult(
            test_type="UV_EXPOSURE",
            status=status,
            pass_rate=round(pass_rate, 4),
            failed_components=failed_components,
            failure_points=failure_points,
            metrics={
                "hours": hours,
                "intensity": intensity,
                "effective_hours": round(eff_hours, 1),
            },
            recommendations=recs,
            severity="WARNING" if failed_components else "INFO",
        )

    def simulate_humidity(self, spec: dict, config: TestConfig) -> TestResult:
        rh_percent = config.parameters.get("rh_percent", 85)
        duration_h = config.parameters.get("duration_hours", 96)
        temp_c = config.parameters.get("temp_celsius", 40)
        condensation = config.parameters.get("condensation", True)

        failed_components: list[str] = []
        failure_points: list[dict] = []
        component_results: list[bool] = []

        corrosion_factor = (
            (rh_percent / 100.0) * (temp_c / 40.0) * (duration_h / 96.0)
        )
        if condensation:
            corrosion_factor *= 1.5

        for comp in spec.get("components", []):
            mat_name = comp.get("material", "ABS").lower()
            is_metal = any(m in mat_name for m in ["steel", "copper", "iron"])
            is_pcb = "pcb" in mat_name or "electronic" in comp.get("name", "").lower()
            is_seal = "rubber" in mat_name

            corrosion_threshold = 0.6 if is_metal else (0.9 if is_pcb else 1.5)
            oxidation_risk = corrosion_factor > 0.7 and is_pcb

            if corrosion_factor > corrosion_threshold or oxidation_risk:
                failed_components.append(comp["id"])
                reason = (
                    "PCB oxidation risk at high humidity and temperature"
                    if oxidation_risk
                    else f"Corrosion risk: factor {corrosion_factor:.2f} exceeds threshold"
                )
                failure_points.append(
                    {
                        "component_id": comp["id"],
                        "reason": reason,
                        "severity": "CRITICAL" if is_pcb else "WARNING",
                    }
                )
                component_results.append(False)
            else:
                component_results.append(True)

        pass_rate = sum(component_results) / max(len(component_results), 1)
        status = (
            "PASS"
            if not failed_components
            else ("PARTIAL" if pass_rate > 0.5 else "FAIL")
        )

        recs: list[str] = []
        if any("PCB" in fp["reason"] or "oxidation" in fp["reason"] for fp in failure_points):
            recs.append("Apply conformal coating to PCB")
            recs.append("Add silica gel desiccant to enclosure")
        if any("corrosion" in fp["reason"].lower() for fp in failure_points):
            recs.append("Switch exposed metal parts to stainless steel 316 or aluminium")

        return TestResult(
            test_type="HUMIDITY_SOAK",
            status=status,
            pass_rate=round(pass_rate, 4),
            failed_components=failed_components,
            failure_points=failure_points,
            metrics={
                "rh_percent": rh_percent,
                "duration_hours": duration_h,
                "temp_celsius": temp_c,
                "corrosion_factor": round(corrosion_factor, 4),
                "condensation": condensation,
            },
            recommendations=recs,
            severity=(
                "CRITICAL"
                if status == "FAIL"
                else ("WARNING" if status == "PARTIAL" else "INFO")
            ),
        )

    def run_full_suite(
        self,
        spec: dict,
        configs: list[TestConfig],
    ) -> list[TestResult]:
        METHOD_MAP = {
            "DROP_TEST": self.simulate_drop,
            "THERMAL_CYCLE": self.simulate_thermal,
            "WATER_INGRESS": self.simulate_water_ingress,
            "BATTERY_DRAIN": self.simulate_battery,
            "VIBRATION": self.simulate_vibration,
            "COMPRESSION": self.simulate_compression,
            "UV_EXPOSURE": self.simulate_uv_exposure,
            "HUMIDITY_SOAK": self.simulate_humidity,
        }
        SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        results: list[TestResult] = []
        for config in configs:
            fn = METHOD_MAP.get(config.test_type)
            if fn is None:
                continue
            try:
                result = fn(spec, config)
                results.append(result)
            except Exception as e:
                results.append(
                    TestResult(
                        test_type=config.test_type,
                        status="FAIL",
                        pass_rate=0.0,
                        failed_components=[],
                        failure_points=[
                            {
                                "component_id": "engine",
                                "reason": str(e),
                                "severity": "CRITICAL",
                            }
                        ],
                        metrics={},
                        recommendations=[
                            "Check spec JSON and test config parameters"
                        ],
                        severity="CRITICAL",
                    )
                )
        results.sort(key=lambda r: (SEVERITY_ORDER.get(r.severity, 2), r.pass_rate))
        return results
