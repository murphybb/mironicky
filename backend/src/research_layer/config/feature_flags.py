from __future__ import annotations

import os

from research_layer.api.schemas.common import ResearchErrorCode

TRUTHY_VALUES = {"1", "true", "yes", "on", "enabled"}

GRAPH_REPORT_FLAG = "RESEARCH_FEATURE_GRAPH_REPORT_ENABLED"
QUERY_API_FLAG = "RESEARCH_FEATURE_QUERY_API_ENABLED"
RAW_BOOTSTRAP_FLAG = "RESEARCH_FEATURE_RAW_BOOTSTRAP_ENABLED"
LOCAL_FIRST_FLAG = "RESEARCH_FEATURE_LOCAL_FIRST_ENABLED"
COMMANDS_FLAG = "RESEARCH_FEATURE_COMMANDS_ENABLED"
EXPORT_FLAG = "RESEARCH_FEATURE_EXPORT_ENABLED"


def is_feature_enabled(flag_name: str) -> bool:
    return os.getenv(flag_name, "").strip().lower() in TRUTHY_VALUES


def feature_disabled_error(flag_name: str) -> dict[str, object]:
    return {
        "status_code": 403,
        "code": ResearchErrorCode.FORBIDDEN.value,
        "message": "research feature is disabled",
        "details": {"feature_flag": flag_name},
    }
