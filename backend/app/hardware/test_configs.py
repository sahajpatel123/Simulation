from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── TestConfig dataclass ──


@dataclass
class TestConfig:
    test_type: str
    parameters: dict[str, Any]
    environment: dict[str, Any]
    severity_weight: float  # 0-1, how critical this test is for category
    display_name: str
    description: str


# ── All 8 test types with full default parameters ──
TEST_DEFAULTS: dict[str, dict[str, Any]] = {
    "DROP_TEST": {
        "parameters": {
            "height_cm": 100,  # 1 metre standard drop
            "surface_type": "concrete",  # concrete|carpet|wood|tile
            "repetitions": 3,
            "drop_angle": "flat",  # flat|corner|edge
        },
        "environment": {"temp_celsius": 25, "humidity_rh": 50},
        "display_name": "Drop Test",
        "description": "Simulates accidental drops onto hard surfaces",
    },
    "THERMAL_CYCLE": {
        "parameters": {
            "min_celsius": -10,
            "max_celsius": 60,
            "cycles": 50,
            "ramp_rate_c_per_min": 5,
        },
        "environment": {"humidity_rh": 50},
        "display_name": "Thermal Cycle",
        "description": "Tests material expansion/contraction under temperature swings",
    },
    "WATER_INGRESS": {
        "parameters": {
            "ip_rating_target": "IP54",  # IP44|IP54|IP65|IP67|IP68
            "duration_minutes": 30,
            "pressure_bar": 0,  # 0 = splash, >0 = submersion
            "depth_m": 0,
        },
        "environment": {"temp_celsius": 25},
        "display_name": "Water Ingress",
        "description": "Verifies IP rating against water and dust penetration",
    },
    "BATTERY_DRAIN": {
        "parameters": {
            "load_profile": "mixed",  # idle|light|mixed|heavy|peak
            "ambient_temp": 25,
            "capacity_mah": 0,  # 0 = read from spec
            "target_runtime_hours": 8,
        },
        "environment": {"temp_celsius": 25, "humidity_rh": 50},
        "display_name": "Battery Drain",
        "description": "Projects runtime at different usage intensities",
    },
    "VIBRATION": {
        "parameters": {
            "frequency_hz": 20,  # 5-500 Hz range
            "amplitude_mm": 0.5,
            "duration_min": 60,
            "axis": "xyz",  # x|y|z|xyz
            "sweep": True,  # sweep through frequencies
        },
        "environment": {"temp_celsius": 25},
        "display_name": "Vibration Test",
        "description": "Simulates transport and operational vibration fatigue",
    },
    "COMPRESSION": {
        "parameters": {
            "force_kg": 50,
            "contact_area_cm2": 10,
            "duration_seconds": 30,
            "load_type": "static",  # static|dynamic|cyclic
        },
        "environment": {"temp_celsius": 25},
        "display_name": "Compression Test",
        "description": "Tests structural integrity under sustained load",
    },
    "UV_EXPOSURE": {
        "parameters": {
            "hours": 500,
            "intensity": "standard",  # low|standard|accelerated
            "uv_index": 8,
            "wavelength": "full_spectrum",
        },
        "environment": {"temp_celsius": 40, "humidity_rh": 60},
        "display_name": "UV Exposure",
        "description": "Tests material discolouration and degradation under UV",
    },
    "HUMIDITY_SOAK": {
        "parameters": {
            "rh_percent": 85,
            "duration_hours": 96,
            "temp_celsius": 40,
            "condensation": True,
        },
        "environment": {"temp_celsius": 40, "humidity_rh": 85},
        "display_name": "Humidity Soak",
        "description": "Tests corrosion, PCB oxidation, and seal integrity at high humidity",
    },
}

# ── Category → recommended test suite ──
# Each hardware category gets a curated default test suite.
# severity_weight determines how critical each test is.

CATEGORY_TEST_SUITES: dict[str, list[tuple[str, float]]] = {
    "consumer_hardware": [
        ("DROP_TEST", 0.90),
        ("VIBRATION", 0.60),
        ("THERMAL_CYCLE", 0.50),
        ("HUMIDITY_SOAK", 0.40),
        ("COMPRESSION", 0.35),
    ],
    "health_hardware": [
        ("DROP_TEST", 0.85),
        ("WATER_INGRESS", 0.90),  # high — wearable health needs IP
        ("THERMAL_CYCLE", 0.70),
        ("HUMIDITY_SOAK", 0.65),
        ("BATTERY_DRAIN", 0.80),
        ("UV_EXPOSURE", 0.30),
    ],
    "wearable": [
        ("DROP_TEST", 0.90),
        ("WATER_INGRESS", 0.95),  # critical for wearables
        ("BATTERY_DRAIN", 0.90),  # critical for wearables
        ("THERMAL_CYCLE", 0.55),
        ("VIBRATION", 0.50),
        ("UV_EXPOSURE", 0.45),
    ],
    "iot_hardware": [
        ("THERMAL_CYCLE", 0.85),  # always on, temperature critical
        ("HUMIDITY_SOAK", 0.80),
        ("WATER_INGRESS", 0.75),
        ("VIBRATION", 0.50),
        ("UV_EXPOSURE", 0.60),  # outdoor IoT devices
    ],
    "b2b_hardware": [
        ("DROP_TEST", 0.70),
        ("VIBRATION", 0.85),  # transport critical
        ("THERMAL_CYCLE", 0.75),
        ("COMPRESSION", 0.80),
        ("HUMIDITY_SOAK", 0.60),
        ("BATTERY_DRAIN", 0.65),
    ],
}


class TestConfigBuilder:
    def defaults_for_category(
        self,
        category: str,
    ) -> list[TestConfig]:
        """
        Returns the recommended test suite for a hardware category.
        Uses CATEGORY_TEST_SUITES to select test types
        and TEST_DEFAULTS for parameter values.
        """
        suite = CATEGORY_TEST_SUITES.get(
            category,
            CATEGORY_TEST_SUITES["consumer_hardware"],
        )
        configs: list[TestConfig] = []
        for test_type, severity_weight in suite:
            defaults = TEST_DEFAULTS[test_type]
            configs.append(
                TestConfig(
                    test_type=test_type,
                    parameters=dict(defaults["parameters"]),
                    environment=dict(defaults["environment"]),
                    severity_weight=severity_weight,
                    display_name=str(defaults["display_name"]),
                    description=str(defaults["description"]),
                )
            )
        return configs

    def custom_config(
        self,
        test_type: str,
        params: dict[str, Any],
        severity_weight: float = 0.5,
    ) -> TestConfig:
        """
        Builds a custom TestConfig merging caller params
        over the defaults for that test_type.
        Unknown test_type raises ValueError.
        """
        if test_type not in TEST_DEFAULTS:
            raise ValueError(
                f"Unknown test_type: {test_type}. Valid: {list(TEST_DEFAULTS.keys())}"
            )
        defaults = TEST_DEFAULTS[test_type]
        merged_params = {**defaults["parameters"], **params}
        return TestConfig(
            test_type=test_type,
            parameters=merged_params,
            environment=dict(defaults["environment"]),
            severity_weight=severity_weight,
            display_name=str(defaults["display_name"]),
            description=str(defaults["description"]),
        )

    def validate_config(
        self,
        config: TestConfig,
    ) -> tuple[bool, str]:
        """
        Validates a TestConfig before saving to DB or
        passing to PhysicsSimulationEngine.
        """
        if config.test_type not in TEST_DEFAULTS:
            return False, f"Unknown test_type: {config.test_type}"

        required_keys = list(TEST_DEFAULTS[config.test_type]["parameters"].keys())
        missing = [k for k in required_keys if k not in config.parameters]
        if missing:
            return False, f"Missing parameters: {missing}"

        if not 0.0 <= config.severity_weight <= 1.0:
            return False, "severity_weight must be 0.0-1.0"

        # Type-specific validation
        if config.test_type == "DROP_TEST":
            if config.parameters.get("height_cm", 0) <= 0:
                return False, "height_cm must be > 0"
            if config.parameters.get("repetitions", 0) <= 0:
                return False, "repetitions must be > 0"

        if config.test_type == "WATER_INGRESS":
            valid_ip = ["IP44", "IP54", "IP65", "IP67", "IP68"]
            if config.parameters.get("ip_rating_target") not in valid_ip:
                return False, f"ip_rating_target must be one of {valid_ip}"

        if config.test_type == "THERMAL_CYCLE":
            if config.parameters.get("min_celsius", 0) >= config.parameters.get("max_celsius", 0):
                return False, "min_celsius must be less than max_celsius"

        if config.test_type == "BATTERY_DRAIN":
            valid_profiles = ["idle", "light", "mixed", "heavy", "peak"]
            if config.parameters.get("load_profile") not in valid_profiles:
                return False, f"load_profile must be one of {valid_profiles}"

        return True, "OK"

    def to_dict(self, config: TestConfig) -> dict[str, Any]:
        return {
            "test_type": config.test_type,
            "display_name": config.display_name,
            "description": config.description,
            "parameters": config.parameters,
            "environment": config.environment,
            "severity_weight": config.severity_weight,
        }
