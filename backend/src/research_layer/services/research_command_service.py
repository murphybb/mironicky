from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.graph.repository import GraphRepository
from research_layer.services.candidate_confirmation_service import (
    CandidateConfirmationService,
)
from research_layer.services.graph_build_service import GraphBuildService
from research_layer.services.package_build_service import PackageBuildService
from research_layer.services.route_generation_service import RouteGenerationService
from research_layer.services.raw_material_bootstrap_service import (
    RawMaterialBootstrapService,
)

COMMAND_NAMES = {
    "ingest",
    "confirm",
    "build_graph",
    "generate_routes",
    "validate",
    "package",
}


class ResearchCommandService:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store
        self._bootstrap_service = RawMaterialBootstrapService(store)
        self._confirmation_service = CandidateConfirmationService(store)
        self._graph_build_service = GraphBuildService(GraphRepository(store))
        self._route_service = RouteGenerationService(store)
        self._package_service = PackageBuildService(store)

    async def run(
        self,
        *,
        workspace_id: str,
        commands: list[dict[str, object]],
        request_id: str,
    ) -> dict[str, object]:
        steps: list[dict[str, object]] = []
        for index, command in enumerate(commands):
            name = str(command.get("name", "")).strip()
            args = command.get("args")
            if not isinstance(args, dict):
                args = {}
            if name not in COMMAND_NAMES:
                steps.append(
                    self._failed_step(
                        index=index,
                        name=name,
                        error_code="research.invalid_request",
                        message="unsupported command",
                    )
                )
                break
            try:
                step_result = await self._run_one(
                    workspace_id=workspace_id,
                    name=name,
                    args=args,
                    request_id=request_id,
                )
                steps.append(
                    {
                        "index": index,
                        "name": name,
                        "status": "succeeded",
                        "resource_refs": step_result.get("resource_refs", []),
                        "job_refs": step_result.get("job_refs", []),
                        "result": step_result.get("result", {}),
                    }
                )
            except Exception as exc:
                steps.append(
                    self._failed_step(
                        index=index,
                        name=name,
                        error_code="research.command_failed",
                        message=str(exc),
                    )
                )
                break
        status = "succeeded" if all(step["status"] == "succeeded" for step in steps) else "failed"
        self._store.emit_event(
            event_name="research_commands_completed",
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="research_command_service",
            step="commands",
            status="completed" if status == "succeeded" else "failed",
            refs={
                "command_names": [str(command.get("name", "")) for command in commands]
            },
            metrics={"step_count": len(steps)},
        )
        return {"workspace_id": workspace_id, "status": status, "steps": steps}

    async def _run_one(
        self,
        *,
        workspace_id: str,
        name: str,
        args: dict[str, object],
        request_id: str,
    ) -> dict[str, object]:
        if name == "ingest":
            materials = args.get("materials")
            if not isinstance(materials, list):
                materials = []
            result = self._bootstrap_service.bootstrap(
                workspace_id=workspace_id,
                materials=[item for item in materials if isinstance(item, dict)],
                request_id=request_id,
                run_extract=bool(args.get("run_extract", False)),
            )
            return {
                "resource_refs": [
                    {"resource_type": "source", "resource_id": item["source_id"]}
                    for item in result.get("items", [])
                    if isinstance(item, dict)
                ],
                "job_refs": [
                    job_ref
                    for item in result.get("items", [])
                    if isinstance(item, dict)
                    for job_ref in item.get("job_refs", [])
                ],
                "result": result,
            }
        if name == "confirm":
            candidate_ids = [str(item) for item in args.get("candidate_ids", [])]
            updated: list[str] = []
            for candidate_id in candidate_ids:
                self._confirmation_service.confirm(
                    workspace_id=workspace_id,
                    candidate_id=candidate_id,
                    request_id=request_id,
                )
                updated.append(candidate_id)
            return {
                "resource_refs": [
                    {"resource_type": "candidate", "resource_id": candidate_id}
                    for candidate_id in updated
                ],
                "result": {"confirmed_candidate_ids": updated},
            }
        if name == "build_graph":
            version = self._graph_build_service.build_workspace_graph(
                workspace_id=workspace_id, request_id=request_id
            )
            return {
                "resource_refs": [
                    {
                        "resource_type": "graph_version",
                        "resource_id": str(version["version_id"]),
                    }
                ],
                "result": version,
            }
        if name == "generate_routes":
            result = await self._route_service.generate_routes(
                workspace_id=workspace_id,
                request_id=request_id,
                reason=str(args.get("reason", "research command")),
                max_candidates=int(args.get("max_candidates", 8)),
                allow_fallback=bool(args.get("allow_fallback", True)),
            )
            return {
                "resource_refs": [
                    {"resource_type": "route", "resource_id": route_id}
                    for route_id in result.get("ranked_route_ids", [])
                ],
                "result": result,
            }
        if name == "validate":
            validation = self._store.create_validation(
                workspace_id=workspace_id,
                target_object=str(args.get("target_object", "workspace")),
                method=str(args.get("method", "manual_review")),
                success_signal=str(args.get("success_signal", "explicit pass")),
                weakening_signal=str(args.get("weakening_signal", "explicit fail")),
            )
            return {
                "resource_refs": [
                    {
                        "resource_type": "validation",
                        "resource_id": str(validation["validation_id"]),
                    }
                ],
                "result": validation,
            }
        if name == "package":
            record = self._package_service.build_snapshot(
                workspace_id=workspace_id,
                title=str(args.get("title", "Research Package")),
                summary=str(args.get("summary", "Research package generated by command.")),
                included_route_ids=[str(item) for item in args.get("route_ids", [])],
                included_node_ids=[str(item) for item in args.get("node_ids", [])],
                included_validation_ids=[
                    str(item) for item in args.get("validation_ids", [])
                ],
                request_id=request_id,
            )
            return {
                "resource_refs": [
                    {
                        "resource_type": "package",
                        "resource_id": str(record["package_id"]),
                    }
                ],
                "result": record,
            }
        raise ValueError("unsupported command")

    def _failed_step(
        self, *, index: int, name: str, error_code: str, message: str
    ) -> dict[str, object]:
        return {
            "index": index,
            "name": name,
            "status": "failed",
            "resource_refs": [],
            "job_refs": [],
            "error": {
                "error_code": error_code,
                "message": message,
                "details": {"command": name},
            },
        }
