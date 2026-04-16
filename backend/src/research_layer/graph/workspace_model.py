from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class GraphWorkspaceModel:
    workspace_id: str
    latest_version_id: str | None
    status: str
    node_count: int
    edge_count: int
    updated_at: datetime | None
