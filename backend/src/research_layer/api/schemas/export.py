from __future__ import annotations

from pydantic import BaseModel


class ResearchExportResponse(BaseModel):
    export_type: str
    format: str
    payload: dict[str, object] | str
