from __future__ import annotations

import time

from fastapi.testclient import TestClient

TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


def wait_for_job_terminal(
    client: TestClient,
    *,
    job_id: str,
    max_attempts: int = 1200,
    sleep_seconds: float = 0.05,
) -> dict[str, object]:
    last_payload: dict[str, object] | None = None
    for _ in range(max_attempts):
        response = client.get(f"/api/v1/research/jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        last_payload = payload
        if str(payload.get("status")) in TERMINAL_JOB_STATUSES:
            return payload
        time.sleep(sleep_seconds)
    raise AssertionError(
        f"job did not reach terminal status within timeout: {job_id}, last={last_payload}"
    )
