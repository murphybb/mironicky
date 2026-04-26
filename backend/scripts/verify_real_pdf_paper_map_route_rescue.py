from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _request_json(
    *,
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 60,
) -> dict[str, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{base_url.rstrip('/')}{path}{query}"
    body = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(raw)
        except json.JSONDecodeError:
            details = {"raw": raw}
        raise RuntimeError(
            f"{method} {path} failed with HTTP {exc.code}: {details}"
        ) from exc


def _poll_job(
    *,
    base_url: str,
    job_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = _request_json(
            method="GET",
            base_url=base_url,
            path=f"/api/v1/research/jobs/{job_id}",
        )
        if str(job.get("status")) in {"succeeded", "completed", "failed", "cancelled"}:
            return job
        time.sleep(poll_interval_seconds)
    raise TimeoutError(f"job {job_id} did not finish within {timeout_seconds}s")


def _candidate_type_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        candidate_type = str(candidate.get("candidate_type") or "unknown")
        counts[candidate_type] = counts.get(candidate_type, 0) + 1
    return dict(sorted(counts.items()))


def _graph_node_type_by_id(graph: dict[str, Any]) -> dict[str, str]:
    return {
        str(node.get("node_id")): str(node.get("node_type"))
        for node in graph.get("nodes", [])
        if node.get("node_id")
    }


def _contains_raw_node_id(route: dict[str, Any], node_ids: set[str]) -> bool:
    def _human_text(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            rendered: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    # node_refs intentionally stores stable machine ids for UI linking.
                    rendered.extend(_human_text(item.get("text")))
                else:
                    rendered.extend(_human_text(item))
            return rendered
        return []

    text_fields = {
        "title": route.get("title"),
        "summary": route.get("summary"),
        "conclusion": route.get("conclusion"),
        "key_supports": route.get("key_supports"),
        "assumptions": route.get("assumptions"),
        "risks": route.get("risks"),
        "next_validation_action": route.get("next_validation_action"),
        "key_strengths": route.get("key_strengths"),
        "key_risks": route.get("key_risks"),
        "open_questions": route.get("open_questions"),
    }
    rendered = json.dumps(
        {key: _human_text(value) for key, value in text_fields.items()},
        ensure_ascii=False,
    )
    return any(node_id in rendered for node_id in node_ids)


def _preflight_workspace_is_empty(
    *,
    base_url: str,
    workspace_id: str,
    failures: list[str],
) -> bool:
    candidates = _request_json(
        method="GET",
        base_url=base_url,
        path="/api/v1/research/candidates",
        params={"workspace_id": workspace_id},
    )
    graph = _request_json(
        method="GET",
        base_url=base_url,
        path=f"/api/v1/research/graph/{workspace_id}",
    )
    routes = _request_json(
        method="GET",
        base_url=base_url,
        path="/api/v1/research/routes",
        params={"workspace_id": workspace_id},
    )

    if candidates.get("items"):
        failures.append("workspace_not_empty_candidates")
    if graph.get("nodes") or graph.get("edges"):
        failures.append("workspace_not_empty_graph")
    if routes.get("items"):
        failures.append("workspace_not_empty_routes")
    return not failures


def run(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf).expanduser().resolve()
    failures: list[str] = []
    report: dict[str, Any] = {
        "base_url": args.base_url,
        "workspace_id": args.workspace_id,
        "pdf": str(pdf_path),
        "steps": {},
        "failures": failures,
    }
    if not pdf_path.exists():
        failures.append(f"pdf_not_found: {pdf_path}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    if not _preflight_workspace_is_empty(
        base_url=args.base_url,
        workspace_id=args.workspace_id,
        failures=failures,
    ):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    imported = _request_json(
        method="POST",
        base_url=args.base_url,
        path="/api/v1/research/sources/import",
        payload={
            "workspace_id": args.workspace_id,
            "source_type": "paper",
            "source_input_mode": "local_file",
            "local_file": {
                "file_name": pdf_path.name,
                "file_content_base64": base64.b64encode(pdf_path.read_bytes()).decode(
                    "ascii"
                ),
                "mime_type": "application/pdf",
            },
            "metadata": {"verification_harness": "paper_map_route_rescue"},
        },
    )
    source_id = str(imported["source_id"])
    report["steps"]["import"] = {
        "source_id": source_id,
        "title": imported.get("title"),
        "chars": len(str(imported.get("content") or "")),
        "parser": (imported.get("metadata") or {}).get("parser"),
    }

    started = _request_json(
        method="POST",
        base_url=args.base_url,
        path=f"/api/v1/research/sources/{source_id}/extract",
        payload={"workspace_id": args.workspace_id, "async_mode": True},
        headers={"x-request-id": f"req_verify_{int(time.time())}"},
    )
    extract_job = _poll_job(
        base_url=args.base_url,
        job_id=str(started["job_id"]),
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    report["steps"]["extract_job"] = extract_job
    if extract_job.get("status") not in {"succeeded", "completed"}:
        failures.append("extraction_failed")
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1

    batch_id = str((extract_job.get("result_ref") or {}).get("resource_id") or "")
    extraction_result = _request_json(
        method="GET",
        base_url=args.base_url,
        path=f"/api/v1/research/sources/{source_id}/extraction-results/{batch_id}",
        params={"workspace_id": args.workspace_id},
    )
    report["steps"]["extraction_result"] = {
        "candidate_batch_id": batch_id,
        "candidate_count": len(extraction_result.get("candidate_ids") or []),
        "provider_backend": extraction_result.get("provider_backend"),
        "provider_model": extraction_result.get("provider_model"),
        "fallback_used": extraction_result.get("fallback_used"),
        "degraded": extraction_result.get("degraded"),
        "degraded_reason": extraction_result.get("degraded_reason"),
    }
    if not extraction_result.get("llm_response_id"):
        failures.append("missing_llm_trace")
    if extraction_result.get("fallback_used"):
        failures.append("extraction_used_fallback")
    if extraction_result.get("degraded"):
        failures.append("extraction_degraded")

    artifacts = _request_json(
        method="GET",
        base_url=args.base_url,
        path=f"/api/v1/research/sources/{source_id}/artifacts",
        params={"workspace_id": args.workspace_id},
    )
    paper_map_artifacts = [
        item for item in artifacts.get("items", []) if item.get("artifact_type") == "paper_map"
    ]
    paper_map_payload: dict[str, Any] = {}
    if paper_map_artifacts:
        try:
            paper_map_payload = json.loads(str(paper_map_artifacts[0].get("content") or "{}"))
        except json.JSONDecodeError:
            failures.append("paper_map_artifact_invalid_json")
    else:
        failures.append("missing_paper_map_artifact")
    report["steps"]["paper_map"] = {
        "artifact_count": len(paper_map_artifacts),
        "keys": sorted(paper_map_payload.keys()),
        "document_type": paper_map_payload.get("document_type"),
    }

    candidates_payload = _request_json(
        method="GET",
        base_url=args.base_url,
        path="/api/v1/research/candidates",
        params={"workspace_id": args.workspace_id, "source_id": source_id},
    )
    candidates = list(candidates_payload.get("items") or [])
    candidate_type_counts = _candidate_type_counts(candidates)
    report["steps"]["candidates"] = {
        "count": len(candidates),
        "type_counts": candidate_type_counts,
    }
    if "conclusion" not in candidate_type_counts and "assumption" not in candidate_type_counts:
        failures.append("missing_conclusion_or_hypothesis_candidate")
    if "evidence" not in candidate_type_counts and "validation" not in candidate_type_counts:
        failures.append("missing_evidence_or_validation_candidate")
    if any(
        item.get("extractor_name") == "deterministic_explicit_paper_claim_extractor"
        for item in candidates
    ):
        failures.append("deterministic_explicit_paper_claim_candidate_present")
    if any(
        "explicit_paper_claim" in json.dumps(item.get("trace_refs") or {}, ensure_ascii=False)
        for item in candidates
    ):
        failures.append("explicit_paper_claim_trace_present")

    confirmed = 0
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        try:
            response = _request_json(
                method="POST",
                base_url=args.base_url,
                path="/api/v1/research/candidates/confirm",
                payload={"workspace_id": args.workspace_id, "candidate_ids": [candidate_id]},
            )
        except RuntimeError as exc:
            if "HTTP 409" in str(exc):
                continue
            raise
        if response.get("status") == "confirmed":
            confirmed += 1
    report["steps"]["confirm"] = {"confirmed_count": confirmed}
    if confirmed == 0:
        failures.append("no_candidates_confirmed")

    built_graph = _request_json(
        method="POST",
        base_url=args.base_url,
        path=f"/api/v1/research/graph/{args.workspace_id}/build",
    )
    graph = _request_json(
        method="GET",
        base_url=args.base_url,
        path=f"/api/v1/research/graph/{args.workspace_id}",
    )
    report["steps"]["graph"] = {
        "version_id": built_graph.get("version_id"),
        "node_count": len(graph.get("nodes") or []),
        "edge_count": len(graph.get("edges") or []),
    }

    generated = _request_json(
        method="POST",
        base_url=args.base_url,
        path="/api/v1/research/routes/generate",
        payload={
            "workspace_id": args.workspace_id,
            "reason": "verify real PDF PaperMap route rescue",
            "max_candidates": args.max_routes,
        },
        timeout_seconds=args.request_timeout_seconds,
    )
    routes_payload = _request_json(
        method="GET",
        base_url=args.base_url,
        path="/api/v1/research/routes",
        params={"workspace_id": args.workspace_id},
    )
    routes = list(routes_payload.get("items") or [])
    node_type_by_id = _graph_node_type_by_id(graph)
    node_ids = set(node_type_by_id)
    route_seed_types = [
        node_type_by_id.get(str(route.get("conclusion_node_id")), "unknown")
        for route in routes
    ]
    support_node_types = [
        node_type_by_id.get(str(node_id), "unknown")
        for route in routes
        for node_id in route.get("key_support_node_ids", [])
    ]
    report["steps"]["routes"] = {
        "generated_count": generated.get("generated_count"),
        "listed_count": len(routes),
        "seed_node_types": route_seed_types,
        "support_node_types": support_node_types,
    }
    if not routes:
        failures.append("no_routes_generated")
    if any(seed_type == "gap" for seed_type in route_seed_types):
        failures.append("gap_route_seed_present")
    if any(support_type not in {"evidence", "validation"} for support_type in support_node_types):
        failures.append("invalid_route_support_node_type")
    if any(_contains_raw_node_id(route, node_ids) for route in routes):
        failures.append("route_summary_raw_node_id_present")
    if any(route.get("summary_generation_mode") != "llm" for route in routes):
        failures.append("route_summary_not_llm")
    if any(route.get("fallback_used") for route in routes):
        failures.append("route_summary_fallback_used")
    if any(route.get("degraded") for route in routes):
        failures.append("route_summary_degraded")

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify real PDF import, PaperMap extraction, graph, and routes."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:1995")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--poll-interval-seconds", type=float, default=2)
    parser.add_argument("--request-timeout-seconds", type=float, default=300)
    parser.add_argument("--max-routes", type=int, default=8)
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
