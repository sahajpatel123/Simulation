"""Shared utilities for simulation architects."""
from __future__ import annotations

def extract_complexity(assumptions: list[dict]) -> float:
    """Infer product complexity from assumption text. Returns 0.0–1.0."""
    for a in assumptions:
        text = str(a.get("text", a.get("assumption", ""))).lower()
        if any(w in text for w in ["complex", "advanced", "many features", "multi-step"]):
            return 0.8
        if any(w in text for w in ["simple", "easy", "minimal", "one feature", "quick", "seamless", "2 minute"]):
            return 0.25
    return 0.5

def extract_assumption_signals(assumptions: list[dict]) -> dict:
    """Extract urgency, switching, regulatory and seasonal intent from assumptions."""
    urgency = 0.5
    switching = 0.5
    regulatory = False
    seasonal = False
    
    for a in assumptions:
        text = str(a.get("text", a.get("assumption", ""))).lower()
        if any(w in text for w in ["urgent", "critical", "must have", "acute", "pain"]):
            urgency = 0.80
        elif any(w in text for w in ["nice to have", "optional", "when time permits"]):
            urgency = 0.25
        if any(w in text for w in ["switching", "migrate", "replace", "move from"]):
            switching = 0.70
        if any(w in text for w in ["regulation", "compliance", "rbi", "sebi", "fda", "approval"]):
            regulatory = True
        if any(w in text for w in ["festival", "diwali", "seasonal", "exam", "summer"]):
            seasonal = True
            
    return {
        "urgency_stated": urgency,
        "switching_stated": switching,
        "regulatory_dep": regulatory,
        "seasonal": seasonal
    }
