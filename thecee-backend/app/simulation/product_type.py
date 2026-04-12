"""Product category enum shared by Conductor and ClusterReweightingEngine."""
from __future__ import annotations

from enum import Enum


class ProductType(str, Enum):
    SAAS                = "saas"
    MARKETPLACE         = "marketplace"
    MOBILE_APP          = "mobile_app"
    DEVELOPER_TOOL      = "developer_tool"
    ENTERPRISE_SOFTWARE = "enterprise_software"
    CONSUMER_HARDWARE   = "consumer_hardware"
    HEALTH_HARDWARE     = "health_hardware"
    IOT_HARDWARE        = "iot_hardware"
    WEARABLE            = "wearable"
    B2B_HARDWARE        = "b2b_hardware"
