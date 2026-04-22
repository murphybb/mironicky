from __future__ import annotations

from research_layer.api.controllers._state_store import ResearchApiStateStore
from research_layer.graph.workspace_model import GraphWorkspaceModel

NODE_STATUS_VALUES = {
    "active",
    "weakened",
    "conflicted",
    "failed",
    "superseded",
    "archived",
}
EDGE_STATUS_VALUES = {
    "active",
    "weakened",
    "conflicted",
    "invalidated",
    "superseded",
    "archived",
}


class GraphRepository:
    def __init__(self, store: ResearchApiStateStore) -> None:
        self._store = store

    def list_confirmed_objects(self, workspace_id: str) -> list[dict[str, object]]:
        return self._store.list_confirmed_objects(workspace_id)

    def list_relation_candidates(
        self, *, workspace_id: str
    ) -> list[dict[str, object]]:
        return self._store.list_relation_candidates(workspace_id=workspace_id)

    def reset_workspace_graph(self, workspace_id: str) -> None:
        self._store.clear_graph_workspace(workspace_id)

    def find_node_by_object_ref(
        self, *, workspace_id: str, object_ref_type: str, object_ref_id: str
    ) -> dict[str, object] | None:
        return self._store.find_graph_node_by_object_ref(
            workspace_id=workspace_id,
            object_ref_type=object_ref_type,
            object_ref_id=object_ref_id,
        )

    def create_node(
        self,
        *,
        workspace_id: str,
        node_type: str,
        object_ref_type: str,
        object_ref_id: str,
        short_label: str,
        full_description: str,
        short_tags: list[str] | None = None,
        visibility: str = "workspace",
        source_refs: list[dict[str, object]] | None = None,
        status: str = "active",
    ) -> dict[str, object]:
        return self._store.create_graph_node(
            workspace_id=workspace_id,
            node_type=node_type,
            object_ref_type=object_ref_type,
            object_ref_id=object_ref_id,
            short_label=short_label,
            full_description=full_description,
            short_tags=short_tags,
            visibility=visibility,
            source_refs=source_refs,
            status=status,
        )

    def get_node(self, node_id: str) -> dict[str, object] | None:
        return self._store.get_graph_node(node_id)

    def list_nodes(self, *, workspace_id: str) -> list[dict[str, object]]:
        return self._store.list_graph_nodes(workspace_id)

    def update_node(
        self,
        *,
        node_id: str,
        short_label: str | None = None,
        full_description: str | None = None,
        short_tags: list[str] | None = None,
        visibility: str | None = None,
        source_refs: list[dict[str, object]] | None = None,
        status: str | None = None,
    ) -> dict[str, object] | None:
        if status is not None and status not in NODE_STATUS_VALUES:
            raise ValueError("invalid graph node status")
        if (
            short_label is None
            and full_description is None
            and short_tags is None
            and visibility is None
            and source_refs is None
            and status is None
        ):
            raise ValueError("empty graph node update")
        return self._store.update_graph_node(
            node_id=node_id,
            short_label=short_label,
            full_description=full_description,
            short_tags=short_tags,
            visibility=visibility,
            source_refs=source_refs,
            status=status,
        )

    def find_edge_by_ref(
        self,
        *,
        workspace_id: str,
        source_node_id: str,
        target_node_id: str,
        edge_type: str,
        object_ref_type: str,
        object_ref_id: str,
    ) -> dict[str, object] | None:
        return self._store.find_graph_edge_by_ref(
            workspace_id=workspace_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge_type=edge_type,
            object_ref_type=object_ref_type,
            object_ref_id=object_ref_id,
        )

    def create_edge(
        self,
        *,
        workspace_id: str,
        source_node_id: str,
        target_node_id: str,
        edge_type: str,
        object_ref_type: str,
        object_ref_id: str,
        strength: float,
        status: str = "active",
    ) -> dict[str, object]:
        return self._store.create_graph_edge(
            workspace_id=workspace_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge_type=edge_type,
            object_ref_type=object_ref_type,
            object_ref_id=object_ref_id,
            strength=strength,
            status=status,
        )

    def get_edge(self, edge_id: str) -> dict[str, object] | None:
        return self._store.get_graph_edge(edge_id)

    def list_edges(self, *, workspace_id: str) -> list[dict[str, object]]:
        return self._store.list_graph_edges(workspace_id)

    def update_edge(
        self, *, edge_id: str, status: str | None, strength: float | None
    ) -> dict[str, object] | None:
        if status is not None and status not in EDGE_STATUS_VALUES:
            raise ValueError("invalid graph edge status")
        if status is None and strength is None:
            raise ValueError("empty graph edge update")
        return self._store.update_graph_edge(
            edge_id=edge_id,
            status=status,
            strength=strength,
        )

    def create_version(
        self,
        *,
        workspace_id: str,
        trigger_type: str,
        change_summary: str,
        diff_payload: dict[str, object],
        request_id: str | None,
    ) -> dict[str, object]:
        return self._store.create_graph_version(
            workspace_id=workspace_id,
            trigger_type=trigger_type,
            change_summary=change_summary,
            diff_payload=diff_payload,
            request_id=request_id,
        )

    def list_versions(self, *, workspace_id: str) -> list[dict[str, object]]:
        return self._store.list_graph_versions(workspace_id)

    def get_version(self, version_id: str) -> dict[str, object] | None:
        return self._store.get_graph_version(version_id)

    def upsert_workspace(
        self,
        *,
        workspace_id: str,
        latest_version_id: str | None,
        status: str,
        node_count: int,
        edge_count: int,
    ) -> GraphWorkspaceModel:
        stored = self._store.upsert_graph_workspace(
            workspace_id=workspace_id,
            latest_version_id=latest_version_id,
            status=status,
            node_count=node_count,
            edge_count=edge_count,
        )
        return GraphWorkspaceModel(
            workspace_id=stored["workspace_id"],
            latest_version_id=stored["latest_version_id"],
            status=stored["status"],
            node_count=int(stored["node_count"]),
            edge_count=int(stored["edge_count"]),
            updated_at=stored["updated_at"],
        )

    def get_workspace(self, workspace_id: str) -> GraphWorkspaceModel | None:
        stored = self._store.get_graph_workspace(workspace_id)
        if stored is None:
            return None
        return GraphWorkspaceModel(
            workspace_id=stored["workspace_id"],
            latest_version_id=stored["latest_version_id"],
            status=stored["status"],
            node_count=int(stored["node_count"]),
            edge_count=int(stored["edge_count"]),
            updated_at=stored["updated_at"],
        )

    def emit_event(
        self,
        *,
        event_name: str,
        request_id: str | None,
        workspace_id: str,
        step: str,
        status: str,
        refs: dict[str, object] | None = None,
        metrics: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
    ) -> None:
        self._store.emit_event(
            event_name=event_name,
            request_id=request_id,
            job_id=None,
            workspace_id=workspace_id,
            component="research_graph",
            step=step,
            status=status,
            refs=refs,
            metrics=metrics,
            error=error,
        )
