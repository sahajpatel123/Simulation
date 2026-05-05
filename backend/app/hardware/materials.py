"""
Step 73 — canonical material library for hardware specs, physics (Step 75), and viewer tinting.

Keys are human-readable canonical names. Claude / UPPER_SNAKE aliases map via ``resolve_material_name``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

FALLBACK_CANONICAL: Final = "ABS"


@dataclass(frozen=True, slots=True)
class MaterialSpec:
    category: str
    density_g_cm3: float
    tensile_strength_mpa: float
    thermal_limit_celsius: float
    water_resistance_ip_rating: str
    cost_per_kg_inr: float
    sustainability_score: float
    typical_use_cases: tuple[str, ...]
    failure_modes: tuple[str, ...]
    aliases: tuple[str, ...]
    render_color_hex: str


MATERIAL_DATABASE: dict[str, MaterialSpec] = {
    # ── PLASTICS ─────────────────────────────────────────────────────
    "ABS": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.05,
        tensile_strength_mpa=40.0,
        thermal_limit_celsius=90.0,
        water_resistance_ip_rating="IP65",
        cost_per_kg_inr=185.0,
        sustainability_score=0.55,
        typical_use_cases=("enclosures", "consumer housings", "automotive interior trim"),
        failure_modes=("UV embrittlement", "stress cracking", "warpage", "chemical crazing"),
        aliases=(
            "abs plastic",
            "acrylonitrile butadiene styrene",
            "abs_shell",
            "abs resin",
            "thermoplastic abs",
            "abs polymer",
        ),
        render_color_hex="#e8e0d0",
    ),
    "Polypropylene (PP)": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=0.905,
        tensile_strength_mpa=35.0,
        thermal_limit_celsius=120.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=120.0,
        sustainability_score=0.62,
        typical_use_cases=("living hinges", "bottle caps", "food containers", "battery brackets"),
        failure_modes=("creep under load", "oxidative degradation", "low temperature embrittlement"),
        aliases=("pp", "polypropylene", "pp homopolymer", "pp copolymer", "olefin plastic"),
        render_color_hex="#e8ebe4",
    ),
    "Polycarbonate (PC)": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.20,
        tensile_strength_mpa=65.0,
        thermal_limit_celsius=135.0,
        water_resistance_ip_rating="IP67",
        cost_per_kg_inr=310.0,
        sustainability_score=0.48,
        typical_use_cases=("transparent covers", "safety lenses", "drone canopies"),
        failure_modes=("notch sensitivity", "stress crazing", "hydrolysis in hot water"),
        aliases=("pc", "polycarbonate", "lexan", "makrolon", "pc lens", "polycarbonate lens"),
        render_color_hex="#c5d4e8",
    ),
    "Nylon 6": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.13,
        tensile_strength_mpa=75.0,
        thermal_limit_celsius=180.0,
        water_resistance_ip_rating="IP65",
        cost_per_kg_inr=260.0,
        sustainability_score=0.52,
        typical_use_cases=("gears", "clips", "wear pads", "cable ties"),
        failure_modes=("moisture absorption", "dimensional change", "fatigue"),
        aliases=("nylon", "nylon 6", "pa6", "polyamide 6", "polyamide"),
        render_color_hex="#c9c4b8",
    ),
    "Nylon 66": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.14,
        tensile_strength_mpa=82.0,
        thermal_limit_celsius=260.0,
        water_resistance_ip_rating="IP65",
        cost_per_kg_inr=290.0,
        sustainability_score=0.50,
        typical_use_cases=("structural clips", "connectors", "high-temp brackets"),
        failure_modes=("hydrolysis", "warping", "fatigue"),
        aliases=("nylon 66", "pa66", "polyamide 66", "pa 66"),
        render_color_hex="#bcb6a8",
    ),
    "PETG": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.27,
        tensile_strength_mpa=53.0,
        thermal_limit_celsius=76.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=195.0,
        sustainability_score=0.58,
        typical_use_cases=("3D printed prototypes", "clear panels", "medical trays"),
        failure_modes=("scratching", "chemical attack by ketones"),
        aliases=("petg", "glycol modified pet", "copolyester"),
        render_color_hex="#dce6f0",
    ),
    "PE-HD": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=0.95,
        tensile_strength_mpa=28.0,
        thermal_limit_celsius=120.0,
        water_resistance_ip_rating="IP66",
        cost_per_kg_inr=105.0,
        sustainability_score=0.68,
        typical_use_cases=("bottles", "chemical tanks", "cutting boards"),
        failure_modes=("environmental stress cracking", "creep"),
        aliases=("hdpe", "high density polyethylene", "polyethylene hd", "pehd"),
        render_color_hex="#d8e0dc",
    ),
    "Polystyrene (PS)": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.05,
        tensile_strength_mpa=45.0,
        thermal_limit_celsius=80.0,
        water_resistance_ip_rating="IP20",
        cost_per_kg_inr=95.0,
        sustainability_score=0.42,
        typical_use_cases=("packaging", "disposable housings", "foam cores"),
        failure_modes=("brittle fracture", "UV yellowing", "solvent attack"),
        aliases=("ps", "polystyrene", "hips", "high impact polystyrene"),
        render_color_hex="#ebe8e2",
    ),
    "PVC": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.38,
        tensile_strength_mpa=52.0,
        thermal_limit_celsius=60.0,
        water_resistance_ip_rating="IP65",
        cost_per_kg_inr=88.0,
        sustainability_score=0.38,
        typical_use_cases=("pipes", "cable insulation", "gaskets"),
        failure_modes=("plasticizer migration", "dehydrochlorination", "notch brittle"),
        aliases=("pvc", "polyvinyl chloride", "vinyl", "uPVC"),
        render_color_hex="#d4d8de",
    ),
    "PEEK": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.32,
        tensile_strength_mpa=95.0,
        thermal_limit_celsius=250.0,
        water_resistance_ip_rating="IP67",
        cost_per_kg_inr=8500.0,
        sustainability_score=0.35,
        typical_use_cases=("implants", "aerospace bushings", "high-temp seals"),
        failure_modes=("cost", "crystallinity variation", "notch sensitivity"),
        aliases=("peek", "polyether ether ketone", "polyetheretherketone"),
        render_color_hex="#b8b5a8",
    ),
    "TPU": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.20,
        tensile_strength_mpa=45.0,
        thermal_limit_celsius=100.0,
        water_resistance_ip_rating="IP67",
        cost_per_kg_inr=420.0,
        sustainability_score=0.50,
        typical_use_cases=("grips", "watch straps", "seals", "bumpers"),
        failure_modes=("hydrolysis", "compression set", "abrasion"),
        aliases=("tpu", "thermoplastic polyurethane", "tpu_grip", "polyurethane elastomer"),
        render_color_hex="#9aa3a8",
    ),
    "PMMA (Acrylic)": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.18,
        tensile_strength_mpa=70.0,
        thermal_limit_celsius=95.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=220.0,
        sustainability_score=0.45,
        typical_use_cases=("displays", "light pipes", "signage"),
        failure_modes=("scratching", "crazing", "brittle crack"),
        aliases=("pmma", "acrylic", "plexiglas", "perspex", "polymethyl methacrylate"),
        render_color_hex="#e4eef8",
    ),
    "PLA": MaterialSpec(
        category="PLASTICS",
        density_g_cm3=1.24,
        tensile_strength_mpa=55.0,
        thermal_limit_celsius=60.0,
        water_resistance_ip_rating="IP20",
        cost_per_kg_inr=350.0,
        sustainability_score=0.78,
        typical_use_cases=("3D printing", "biodegradable prototypes"),
        failure_modes=("low heat deflection", "moisture uptake", "creep"),
        aliases=("pla", "polylactic acid", "polylactide"),
        render_color_hex="#e6dcc8",
    ),
    # ── METALS ───────────────────────────────────────────────────────
    "Aluminium 6061": MaterialSpec(
        category="METALS",
        density_g_cm3=2.70,
        tensile_strength_mpa=310.0,
        thermal_limit_celsius=650.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=320.0,
        sustainability_score=0.60,
        typical_use_cases=("extrusions", "heat sinks", "drone frames", "enclosures"),
        failure_modes=("galvanic corrosion", "fatigue cracks", "anodise seal failure"),
        aliases=(
            "aluminum",
            "aluminium",
            "al 6061",
            "aluminum alloy",
            "6061",
            "aluminum 6061",
            "aluminium alloy",
            "al6061",
            "aluminum_6061",
        ),
        render_color_hex="#a8b4c0",
    ),
    "Aluminium 7075": MaterialSpec(
        category="METALS",
        density_g_cm3=2.81,
        tensile_strength_mpa=570.0,
        thermal_limit_celsius=480.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=520.0,
        sustainability_score=0.55,
        typical_use_cases=("aircraft fittings", "high-stress brackets", "bike parts"),
        failure_modes=("stress corrosion cracking", "notch sensitivity"),
        aliases=("7075", "al 7075", "aluminum 7075", "aa7075"),
        render_color_hex="#9aa8b4",
    ),
    "Steel 304": MaterialSpec(
        category="METALS",
        density_g_cm3=8.00,
        tensile_strength_mpa=520.0,
        thermal_limit_celsius=870.0,
        water_resistance_ip_rating="IP66",
        cost_per_kg_inr=180.0,
        sustainability_score=0.58,
        typical_use_cases=("fasteners", "medical instruments", "kitchen appliances"),
        failure_modes=("chloride pitting", "galvanic corrosion", "work hardening limits"),
        aliases=(
            "steel",
            "stainless steel",
            "304 stainless",
            "ss304",
            "stainless_304",
            "aisi 304",
            "steel 304",
        ),
        render_color_hex="#7a8a94",
    ),
    "Steel 316": MaterialSpec(
        category="METALS",
        density_g_cm3=8.00,
        tensile_strength_mpa=485.0,
        thermal_limit_celsius=870.0,
        water_resistance_ip_rating="IP68",
        cost_per_kg_inr=240.0,
        sustainability_score=0.56,
        typical_use_cases=("marine hardware", "implant tooling", "chemical plant"),
        failure_modes=("crevice corrosion", "sensitisation if overheated"),
        aliases=("316", "ss316", "marine grade stainless", "aisi 316"),
        render_color_hex="#6d7c86",
    ),
    "Copper C110": MaterialSpec(
        category="METALS",
        density_g_cm3=8.96,
        tensile_strength_mpa=220.0,
        thermal_limit_celsius=1085.0,
        water_resistance_ip_rating="IP20",
        cost_per_kg_inr=920.0,
        sustainability_score=0.45,
        typical_use_cases=("bus bars", "heat spreaders", "RF shields"),
        failure_modes=("oxidation", "galvanic corrosion", "work hardening"),
        aliases=("copper", "cu", "c110", "electrolytic copper", "ofhc", "copper bar"),
        render_color_hex="#b87333",
    ),
    "Brass": MaterialSpec(
        category="METALS",
        density_g_cm3=8.50,
        tensile_strength_mpa=350.0,
        thermal_limit_celsius=900.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=560.0,
        sustainability_score=0.48,
        typical_use_cases=("valves", "decorative trim", "electrical terminals"),
        failure_modes=("dezincification", "stress corrosion"),
        aliases=("brass", "cartridge brass", "cu-zn"),
        render_color_hex="#c9a961",
    ),
    "Titanium Grade 5": MaterialSpec(
        category="METALS",
        density_g_cm3=4.43,
        tensile_strength_mpa=950.0,
        thermal_limit_celsius=1668.0,
        water_resistance_ip_rating="IP67",
        cost_per_kg_inr=12000.0,
        sustainability_score=0.40,
        typical_use_cases=("aerospace fasteners", "implants", "premium frames"),
        failure_modes=("galling", "notch sensitivity", "cost"),
        aliases=("titanium", "ti-6al-4v", "ti6al4v", "grade 5 titanium", "ti gr5"),
        render_color_hex="#8a9ba8",
    ),
    "Zinc die-cast": MaterialSpec(
        category="METALS",
        density_g_cm3=6.90,
        tensile_strength_mpa=280.0,
        thermal_limit_celsius=380.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=210.0,
        sustainability_score=0.42,
        typical_use_cases=("complex housings", "gears", "latches"),
        failure_modes=("porosity", "creep", "corrosion without plating"),
        aliases=("zamak", "zinc alloy", "die cast zinc", "zinc diecast"),
        render_color_hex="#9a9ea2",
    ),
    "Magnesium AZ31": MaterialSpec(
        category="METALS",
        density_g_cm3=1.78,
        tensile_strength_mpa=260.0,
        thermal_limit_celsius=450.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=480.0,
        sustainability_score=0.52,
        typical_use_cases=("laptop shells", "lightweight brackets", "drone arms"),
        failure_modes=("galvanic corrosion", "flammability chips", "creep"),
        aliases=("magnesium", "az31", "mg alloy", "mg az31"),
        render_color_hex="#aeb4b8",
    ),
    "Galvanized steel": MaterialSpec(
        category="METALS",
        density_g_cm3=7.85,
        tensile_strength_mpa=400.0,
        thermal_limit_celsius=420.0,
        water_resistance_ip_rating="IP55",
        cost_per_kg_inr=95.0,
        sustainability_score=0.50,
        typical_use_cases=("sheet metal chassis", "brackets", "racks"),
        failure_modes=("white rust", "edge corrosion", "weld burn-off of zinc"),
        aliases=("galvanised steel", "gi sheet", "zinc coated steel", "galvanized sheet"),
        render_color_hex="#8b9298",
    ),
    # ── COMPOSITES ───────────────────────────────────────────────────
    "Carbon fibre": MaterialSpec(
        category="COMPOSITES",
        density_g_cm3=1.60,
        tensile_strength_mpa=1500.0,
        thermal_limit_celsius=250.0,
        water_resistance_ip_rating="IP65",
        cost_per_kg_inr=4500.0,
        sustainability_score=0.32,
        typical_use_cases=("racing frames", "aerospace panels", "tripod legs"),
        failure_modes=("delamination", "impact damage", "UV matrix degradation"),
        aliases=(
            "carbon fiber",
            "carbon fibre",
            "cf",
            "carbon composite",
            "carbon fiber reinforced",
            "cfrp",
        ),
        render_color_hex="#1a1a2e",
    ),
    "Fibreglass epoxy": MaterialSpec(
        category="COMPOSITES",
        density_g_cm3=1.90,
        tensile_strength_mpa=340.0,
        thermal_limit_celsius=180.0,
        water_resistance_ip_rating="IP65",
        cost_per_kg_inr=380.0,
        sustainability_score=0.44,
        typical_use_cases=("boat hulls", "radomes", "industrial tanks"),
        failure_modes=("matrix microcracks", "osmosis blistering"),
        aliases=("fiberglass", "fibreglass", "gfrp", "glass reinforced plastic", "frp"),
        render_color_hex="#6b7a8c",
    ),
    "GFRP sheet": MaterialSpec(
        category="COMPOSITES",
        density_g_cm3=1.85,
        tensile_strength_mpa=300.0,
        thermal_limit_celsius=160.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=290.0,
        sustainability_score=0.46,
        typical_use_cases=("flat structural panels", "automotive floors"),
        failure_modes=("interlaminar shear", "drill breakout"),
        aliases=("glass fiber sheet", "fiberglass sheet", "grp sheet"),
        render_color_hex="#758696",
    ),
    "Kevlar aramid": MaterialSpec(
        category="COMPOSITES",
        density_g_cm3=1.44,
        tensile_strength_mpa=3600.0,
        thermal_limit_celsius=400.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=6200.0,
        sustainability_score=0.36,
        typical_use_cases=("ballistic panels", "cables", "wear liners"),
        failure_modes=("compressive kink", "hydrolysis in acid"),
        aliases=("kevlar", "aramid", "para-aramid", "twaron"),
        render_color_hex="#d4c4a8",
    ),
    # ── ELECTRONICS ─────────────────────────────────────────────────
    "FR4 PCB": MaterialSpec(
        category="ELECTRONICS",
        density_g_cm3=1.85,
        tensile_strength_mpa=300.0,
        thermal_limit_celsius=130.0,
        water_resistance_ip_rating="IP20",
        cost_per_kg_inr=950.0,
        sustainability_score=0.42,
        typical_use_cases=("motherboards", "modules", "rigid PCBs"),
        failure_modes=("via barrel cracking", "CAF", "thermal cycling delamination"),
        aliases=("pcb", "fr4", "pcb_fr4", "fr-4", "printed circuit board", "fiberglass pcb"),
        render_color_hex="#1a6b3a",
    ),
    "Flex PCB": MaterialSpec(
        category="ELECTRONICS",
        density_g_cm3=1.72,
        tensile_strength_mpa=180.0,
        thermal_limit_celsius=200.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=2200.0,
        sustainability_score=0.40,
        typical_use_cases=("folding hinges", "camera flex", "wearable interconnect"),
        failure_modes=("bend fatigue", "adhesive debond", "tear"),
        aliases=("flex pcb", "fpc", "flexible pcb", "polyimide flex", "kapton flex"),
        render_color_hex="#2d4a3a",
    ),
    "Silicone rubber": MaterialSpec(
        category="ELECTRONICS",
        density_g_cm3=1.15,
        tensile_strength_mpa=9.0,
        thermal_limit_celsius=230.0,
        water_resistance_ip_rating="IP68",
        cost_per_kg_inr=780.0,
        sustainability_score=0.48,
        typical_use_cases=("gaskets", "keyboard mats", "watch seals"),
        failure_modes=("compression set", "tear propagation", "swelling in oils"),
        aliases=("silicone", "silicone rubber", "silicone_gasket", "vmq", "pdms rubber"),
        render_color_hex="#4a9e6a",
    ),
    "Copper winding": MaterialSpec(
        category="ELECTRONICS",
        density_g_cm3=8.96,
        tensile_strength_mpa=200.0,
        thermal_limit_celsius=1085.0,
        water_resistance_ip_rating="IP20",
        cost_per_kg_inr=880.0,
        sustainability_score=0.46,
        typical_use_cases=("motor windings", "coils", "transformers"),
        failure_modes=("insulation breakdown", "hot spot oxidation"),
        aliases=("magnet wire", "enameled copper", "copper wire winding", "litz"),
        render_color_hex="#c47a3a",
    ),
    "Aluminium heatsink": MaterialSpec(
        category="ELECTRONICS",
        density_g_cm3=2.70,
        tensile_strength_mpa=310.0,
        thermal_limit_celsius=650.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=340.0,
        sustainability_score=0.58,
        typical_use_cases=("LED thermal", "CPU spreaders", "power electronics"),
        failure_modes=("oxidation film change", "interface voids"),
        aliases=("heatsink", "heat sink", "aluminum heatsink", "aluminium heatsink"),
        render_color_hex="#9caab8",
    ),
    "Lithium cell casing": MaterialSpec(
        category="ELECTRONICS",
        density_g_cm3=2.70,
        tensile_strength_mpa=270.0,
        thermal_limit_celsius=200.0,
        water_resistance_ip_rating="IP67",
        cost_per_kg_inr=410.0,
        sustainability_score=0.35,
        typical_use_cases=("18650 cans", "pouch frames", "battery modules"),
        failure_modes=("dent short", "vent weld leak", "thermal runaway propagation"),
        aliases=("lithium cell", "battery can", "18650 shell", "lithium_cell"),
        render_color_hex="#5c6068",
    ),
    "Ceramic substrate": MaterialSpec(
        category="ELECTRONICS",
        density_g_cm3=3.90,
        tensile_strength_mpa=300.0,
        thermal_limit_celsius=1500.0,
        water_resistance_ip_rating="IP65",
        cost_per_kg_inr=1800.0,
        sustainability_score=0.38,
        typical_use_cases=("LED COB", "power modules", "RF substrates"),
        failure_modes=("brittle crack", "CTE mismatch delamination"),
        aliases=("alumina substrate", "al2o3 ceramic", "dbc ceramic"),
        render_color_hex="#e8e4dc",
    ),
    "Magnet wire enamel": MaterialSpec(
        category="ELECTRONICS",
        density_g_cm3=1.40,
        tensile_strength_mpa=120.0,
        thermal_limit_celsius=200.0,
        water_resistance_ip_rating="IP20",
        cost_per_kg_inr=520.0,
        sustainability_score=0.44,
        typical_use_cases=("motor windings", "solenoids"),
        failure_modes=("pinholes", "thermal class overrun"),
        aliases=("magnet wire", "winding wire", "enameled wire"),
        render_color_hex="#6b4423",
    ),
    # ── OTHER / STRUCTURAL ───────────────────────────────────────────
    "Tempered glass": MaterialSpec(
        category="OTHER",
        density_g_cm3=2.50,
        tensile_strength_mpa=120.0,
        thermal_limit_celsius=300.0,
        water_resistance_ip_rating="IP67",
        cost_per_kg_inr=120.0,
        sustainability_score=0.55,
        typical_use_cases=("phone fronts", "appliance panels", "sensors cover"),
        failure_modes=("edge chips", "nick propagation", "spontaneous rare failure"),
        aliases=("glass", "tempered", "gorilla glass", "soda lime tempered"),
        render_color_hex="#a8c0d8",
    ),
    "Alumina ceramic": MaterialSpec(
        category="OTHER",
        density_g_cm3=3.95,
        tensile_strength_mpa=300.0,
        thermal_limit_celsius=1700.0,
        water_resistance_ip_rating="IP65",
        cost_per_kg_inr=1400.0,
        sustainability_score=0.42,
        typical_use_cases=("wear inserts", "spark plugs insulator", "nozzles"),
        failure_modes=("brittle fracture", "thermal shock"),
        aliases=("alumina", "al2o3", "technical ceramic"),
        render_color_hex="#d2d0cc",
    ),
    "EVA foam": MaterialSpec(
        category="OTHER",
        density_g_cm3=0.05,
        tensile_strength_mpa=2.5,
        thermal_limit_celsius=70.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=180.0,
        sustainability_score=0.52,
        typical_use_cases=("padding", "insoles", "case inserts"),
        failure_modes=("compression set", "tear", "UV shrinkage"),
        aliases=("eva", "ethylene vinyl acetate", "foam insert"),
        render_color_hex="#c4b8a4",
    ),
    "MDF": MaterialSpec(
        category="OTHER",
        density_g_cm3=0.75,
        tensile_strength_mpa=35.0,
        thermal_limit_celsius=120.0,
        water_resistance_ip_rating="IP20",
        cost_per_kg_inr=45.0,
        sustainability_score=0.48,
        typical_use_cases=("speaker boxes", "furniture", "fixtures"),
        failure_modes=("swelling in moisture", "fastener pull-out"),
        aliases=("mdf", "medium density fiberboard", "fiberboard"),
        render_color_hex="#b59b7a",
    ),
    "Cotton textile": MaterialSpec(
        category="OTHER",
        density_g_cm3=0.55,
        tensile_strength_mpa=0.4,
        thermal_limit_celsius=150.0,
        water_resistance_ip_rating="IP20",
        cost_per_kg_inr=220.0,
        sustainability_score=0.72,
        typical_use_cases=("straps", "wearables lining", "pouches"),
        failure_modes=("abrasion", "mildew", "stretch set"),
        aliases=("cotton", "woven cotton", "fabric strap"),
        render_color_hex="#d6c4a8",
    ),
    "PU leather": MaterialSpec(
        category="OTHER",
        density_g_cm3=1.05,
        tensile_strength_mpa=25.0,
        thermal_limit_celsius=90.0,
        water_resistance_ip_rating="IP54",
        cost_per_kg_inr=160.0,
        sustainability_score=0.40,
        typical_use_cases=("headphone pads", "furniture", "watch straps"),
        failure_modes=("peeling", "hydrolysis", "surface cracking"),
        aliases=("pu leather", "vegan leather", "synthetic leather", "pleather"),
        render_color_hex="#6b5344",
    ),
}

_ALIAS_RESOLVE_CACHE: dict[str, str] | None = None


def _build_alias_lookup() -> dict[str, str]:
    out: dict[str, str] = {}
    for canon, spec in MATERIAL_DATABASE.items():
        out[re.sub(r"\s+", " ", canon.strip().lower())] = canon
        for a in spec.aliases:
            key = re.sub(r"\s+", " ", str(a).strip().lower())
            if key:
                out[key] = canon
    return out


def _alias_lookup() -> dict[str, str]:
    global _ALIAS_RESOLVE_CACHE
    if _ALIAS_RESOLVE_CACHE is None:
        _ALIAS_RESOLVE_CACHE = _build_alias_lookup()
    return _ALIAS_RESOLVE_CACHE


def resolve_material_name(raw_name: str) -> str:
    """
    Map Claude / user free-text or UPPER_SNAKE tokens to a canonical MATERIAL_DATABASE key.
    Falls back to ABS when nothing is close enough.
    """
    s = raw_name.strip().lower()
    if not s:
        return FALLBACK_CANONICAL
    idx = _alias_lookup()
    norm = re.sub(r"\s+", " ", s)
    if norm in idx:
        return idx[norm]
    snake = norm.replace(" ", "_")
    if snake in idx:
        return idx[snake]
    for token in re.split(r"[^a-z0-9]+", norm):
        if not token:
            continue
        if token in idx:
            return idx[token]
    best_key = FALLBACK_CANONICAL
    best_r = 0.0
    for canon, spec in MATERIAL_DATABASE.items():
        for t in (canon, *spec.aliases):
            tl = str(t).lower()
            r = SequenceMatcher(None, norm, tl).ratio()
            if r > best_r:
                best_r = r
                best_key = canon
            r2 = SequenceMatcher(None, norm, tl.replace("_", " ")).ratio()
            if r2 > best_r:
                best_r = r2
                best_key = canon
    if best_r >= 0.48:
        return best_key
    return FALLBACK_CANONICAL


def get_material(name: str) -> MaterialSpec:
    """Return the canonical spec for ``name`` (any alias accepted)."""
    key = resolve_material_name(name)
    return MATERIAL_DATABASE.get(key, MATERIAL_DATABASE[FALLBACK_CANONICAL])


def get_material_color(material_name: str) -> str:
    """Hex tint for Step 72 zone colouring; neutral grey if unknown."""
    key = resolve_material_name(material_name)
    spec = MATERIAL_DATABASE.get(key)
    if spec is None:
        return "#808080"
    return spec.render_color_hex


def materials_for_category(category: str) -> list[tuple[str, MaterialSpec]]:
    cat = category.strip().upper()
    return [(k, v) for k, v in MATERIAL_DATABASE.items() if v.category.upper() == cat]


def estimate_component_cost(material: str, volume_cm3: float) -> float:
    """Rough INR from volume (cm³) and bulk material cost (ignores scrap/yield)."""
    spec = get_material(material)
    vol = max(0.0, float(volume_cm3))
    mass_g = vol * spec.density_g_cm3
    return round((mass_g / 1000.0) * spec.cost_per_kg_inr, 2)
