from __future__ import annotations

import pytest

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.services.package_build_service import (
    PackageBuildService,
    PackageBuildServiceError,
)


def _build_store(tmp_path) -> ResearchApiStateStore:
    return ResearchApiStateStore(db_path=str(tmp_path / "slice11_package_services.sqlite3"))


def _seed_slice11_workspace(
    store: ResearchApiStateStore, workspace_id: str
) -> dict[str, str]:
    validation = store.create_validation(
        workspace_id=workspace_id,
        target_object="route:seed",
        method="run deterministic benchmark",
        success_signal="support increases",
        weakening_signal="support decreases",
    )
    evidence_node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="evidence",
        object_ref_type="research_evidence",
        object_ref_id="evidence_seed_01",
        short_label="Evidence seed",
        full_description="Seed evidence node for package build tests",
        status="active",
    )
    private_node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="private_dependency",
        object_ref_type="private_note",
        object_ref_id="private_seed_01",
        short_label="Private dependency seed",
        full_description="Private dependency that must be transformed to public gap",
        status="active",
    )
    validation_node = store.create_graph_node(
        workspace_id=workspace_id,
        node_type="validation",
        object_ref_type="validation_action",
        object_ref_id=str(validation["validation_id"]),
        short_label="Validation seed",
        full_description="Validation node linked to seeded validation action",
        status="active",
    )
    route = store.create_route(
        workspace_id=workspace_id,
        title="Slice11 Route Seed",
        summary="Route for testing package snapshot build",
        status="active",
        support_score=0.72,
        risk_score=0.28,
        progressability_score=0.66,
        conclusion="Route conclusion seeded for package",
        key_supports=["support evidence"],
        assumptions=["seed assumption"],
        risks=["seed risk"],
        next_validation_action="run deterministic benchmark",
        conclusion_node_id=str(evidence_node["node_id"]),
        route_node_ids=[
            str(evidence_node["node_id"]),
            str(private_node["node_id"]),
            str(validation_node["node_id"]),
        ],
        key_support_node_ids=[str(evidence_node["node_id"])],
        key_assumption_node_ids=[],
        risk_node_ids=[str(private_node["node_id"])],
        next_validation_node_id=str(validation_node["node_id"]),
        version_id="ver_slice11_seed",
    )
    return {
        "route_id": str(route["route_id"]),
        "evidence_node_id": str(evidence_node["node_id"]),
        "private_node_id": str(private_node["node_id"]),
        "validation_id": str(validation["validation_id"]),
    }


def test_slice11_package_build_creates_snapshot_with_private_gap_and_traceability(
    tmp_path,
) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice11_pkg_build"
    seeded = _seed_slice11_workspace(store, workspace_id)
    service = PackageBuildService(store)

    package = service.build_snapshot(
        workspace_id=workspace_id,
        title="Slice11 Package",
        summary="snapshot for publish",
        included_route_ids=[seeded["route_id"]],
        included_node_ids=[],
        included_validation_ids=[],
        request_id="req_slice11_pkg_build",
    )

    assert package["workspace_id"] == workspace_id
    assert package["snapshot_type"] == "research_package_snapshot"
    assert package["snapshot_version"] == "slice11.v1"
    assert package["replay_ready"] is True
    assert seeded["route_id"] in package["included_route_ids"]
    assert seeded["private_node_id"] not in package["included_node_ids"]
    assert package["private_dependency_flags"]
    assert package["public_gap_nodes"]
    flag = package["private_dependency_flags"][0]
    gap = package["public_gap_nodes"][0]
    assert flag["private_node_id"] == seeded["private_node_id"]
    assert flag["replacement_gap_node_id"] == gap["node_id"]
    assert gap["trace_refs"]["private_node_id"] == seeded["private_node_id"]
    assert gap["trace_refs"]["route_ids"]
    replay = package["snapshot_payload"]
    assert replay["package_id"] == package["package_id"]
    assert replay["private_dependency_flags"][0]["private_node_id"] == seeded["private_node_id"]
    assert replay["public_gap_nodes"][0]["node_id"] == gap["node_id"]
    assert replay["pre_publish_review"]["readiness"] in {
        "ready",
        "review_required",
        "blocked",
    }
    assert "blocking_issues" in replay["pre_publish_review"]
    assert "warnings" in replay["pre_publish_review"]
    assert "suggestions" in replay["pre_publish_review"]
    replay_route = replay["routes"][0]
    assert seeded["private_node_id"] not in replay_route["route_node_ids"]
    assert gap["node_id"] in replay_route["route_node_ids"]
    assert replay["traceability_refs"]["replacement_map"][seeded["private_node_id"]] == gap["node_id"]
    assert (
        replay["traceability_refs"]["pre_publish_review_refs"]["readiness"]
        == replay["pre_publish_review"]["readiness"]
    )


def test_slice11_package_build_rejects_empty_input_and_missing_route(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice11_pkg_errors"
    service = PackageBuildService(store)

    with pytest.raises(PackageBuildServiceError) as empty_exc:
        service.build_snapshot(
            workspace_id=workspace_id,
            title="Empty package",
            summary="invalid",
            included_route_ids=[],
            included_node_ids=[],
            included_validation_ids=[],
            request_id="req_slice11_empty",
        )
    assert empty_exc.value.status_code == 400
    assert empty_exc.value.error_code == "research.invalid_request"

    with pytest.raises(PackageBuildServiceError) as missing_route_exc:
        service.build_snapshot(
            workspace_id=workspace_id,
            title="Missing route package",
            summary="invalid route ref",
            included_route_ids=["route_missing"],
            included_node_ids=[],
            included_validation_ids=[],
            request_id="req_slice11_missing_route",
        )
    assert missing_route_exc.value.status_code == 404
    assert missing_route_exc.value.error_code == "research.not_found"


def test_slice11_publish_creates_publish_result_and_marks_package_published(tmp_path) -> None:
    store = _build_store(tmp_path)
    workspace_id = "ws_slice11_publish"
    seeded = _seed_slice11_workspace(store, workspace_id)
    service = PackageBuildService(store)

    package = service.build_snapshot(
        workspace_id=workspace_id,
        title="Slice11 Publish Package",
        summary="publish snapshot package",
        included_route_ids=[seeded["route_id"]],
        included_node_ids=[],
        included_validation_ids=[],
        request_id="req_slice11_publish_build",
    )
    publish_result = service.publish_snapshot(
        workspace_id=workspace_id,
        package_id=str(package["package_id"]),
        request_id="req_slice11_publish",
        job_id="job_slice11_publish",
        async_mode=True,
    )
    refreshed = store.get_package(str(package["package_id"]))
    assert refreshed is not None
    assert refreshed["status"] == "published"
    assert refreshed["published_at"] is not None
    assert publish_result["package_id"] == package["package_id"]
    assert publish_result["publish_result_id"]
    stored_result = store.get_package_publish_result(str(publish_result["publish_result_id"]))
    assert stored_result is not None
    assert stored_result["package_id"] == package["package_id"]
    assert stored_result["workspace_id"] == workspace_id
