from __future__ import annotations

import json
import re
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

from research_layer.api.schemas.common import WORKSPACE_ID_PATTERN, ResearchErrorCode

WORKSPACE_ID_RE = re.compile(WORKSPACE_ID_PATTERN)


def parse_model(model_cls: type[BaseModel], payload: dict[str, object]) -> BaseModel:
    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        raise_http_error(
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="request validation failed",
            details={"errors": exc.errors()},
        )


async def load_json_object(request: Request) -> dict[str, object]:
    raw_body = await request.body()
    if not raw_body or not raw_body.strip():
        raise_http_error(
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="request validation failed",
            details={"errors": [{"loc": ["body"], "msg": "empty request body"}]},
        )
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise_http_error(
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="request validation failed",
            details={
                "errors": [
                    {
                        "loc": ["body"],
                        "msg": "invalid json body",
                        "details": {
                            "line": exc.lineno,
                            "column": exc.colno,
                            "pos": exc.pos,
                        },
                    }
                ]
            },
        )
    if not isinstance(payload, dict):
        raise_http_error(
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="request validation failed",
            details={
                "errors": [
                    {"loc": ["body"], "msg": "request body must be a JSON object"}
                ]
            },
        )
    return payload


async def parse_request_model(
    request: Request, model_cls: type[BaseModel]
) -> BaseModel:
    return parse_model(model_cls, await load_json_object(request))


def raise_http_error(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "details": details or {}},
    )


def ensure(
    condition: bool,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> None:
    if not condition:
        raise_http_error(
            status_code=status_code, code=code, message=message, details=details
        )


def validate_workspace_id(workspace_id: str | None) -> str:
    if workspace_id is None or not WORKSPACE_ID_RE.fullmatch(workspace_id):
        raise_http_error(
            status_code=400,
            code=ResearchErrorCode.INVALID_REQUEST.value,
            message="request validation failed",
            details={
                "errors": [{"loc": ["workspace_id"], "msg": "invalid workspace_id"}]
            },
        )
    return workspace_id


def get_request_id(raw_request_id: str | None) -> str:
    if raw_request_id and raw_request_id.strip():
        return raw_request_id.strip()
    return f"req_{uuid4().hex[:12]}"


def error_payload_from_exception(exc: Exception) -> dict[str, object]:
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return {
            "error_code": str(detail.get("error_code", "research.unhandled_error")),
            "message": str(detail.get("message", "request failed")),
            "details": (
                detail.get("details")
                if isinstance(detail.get("details"), dict)
                else {}
            ),
        }
    return {
        "error_code": "research.unhandled_error",
        "message": str(exc),
        "details": {},
    }
