from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from core.component.llm.llm_adapter.message import ChatMessage, MessageRole


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


@dataclass(slots=True)
class OntologyPromptRenderResult:
    ontology_path_context: dict[str, object]
    rendered_prompt: str


def load_prompt_template(file_name: str) -> str:
    path = PROMPT_DIR / file_name
    return path.read_text(encoding="utf-8").lstrip("\ufeff")


def render_prompt_template(template: str, variables: dict[str, object]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def render_prompt_with_ontology_paths(
    *,
    template: str,
    variables: dict[str, object],
    resolved_triggers: list[dict[str, object]],
    graph_nodes: list[dict[str, object]],
    graph_edges: list[dict[str, object]],
    max_depth: int = 3,
    max_paths: int = 12,
) -> OntologyPromptRenderResult:
    base_prompt = render_prompt_template(template, variables)
    ontology_context = _build_ontology_path_context(
        resolved_triggers=resolved_triggers,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        max_depth=max_depth,
        max_paths=max_paths,
    )
    rendered_prompt = (
        f"{base_prompt.rstrip()}\n\n"
        "ontology_path_context_json:\n"
        f"{json.dumps(ontology_context, ensure_ascii=False, default=str)}\n"
    )
    return OntologyPromptRenderResult(
        ontology_path_context=ontology_context,
        rendered_prompt=rendered_prompt,
    )


def _build_ontology_path_context(
    *,
    resolved_triggers: list[dict[str, object]],
    graph_nodes: list[dict[str, object]],
    graph_edges: list[dict[str, object]],
    max_depth: int,
    max_paths: int,
) -> dict[str, object]:
    depth_limit = max(0, int(max_depth))
    path_limit = max(0, int(max_paths))
    node_map: dict[str, dict[str, object]] = {}
    for node in graph_nodes:
        node_id = str(node.get("node_id", "")).strip()
        if node_id:
            node_map[node_id] = node
    edge_by_id: dict[str, dict[str, object]] = {}
    adjacency: dict[str, list[dict[str, object]]] = {}
    for edge in graph_edges:
        edge_id = str(edge.get("edge_id", "")).strip()
        source = str(edge.get("source_node_id", "")).strip()
        target = str(edge.get("target_node_id", "")).strip()
        if not edge_id or not source or not target:
            continue
        if source not in node_map or target not in node_map:
            continue
        status = str(edge.get("status", "")).strip()
        if status and status != "active":
            continue
        normalized = {
            "edge_id": edge_id,
            "source_node_id": source,
            "target_node_id": target,
            "edge_type": str(edge.get("edge_type", "")).strip(),
            "strength": edge.get("strength"),
            "status": status or "active",
        }
        edge_by_id[edge_id] = normalized
        adjacency.setdefault(source, []).append(normalized)
    for source in adjacency:
        adjacency[source].sort(
            key=lambda item: (
                str(item["target_node_id"]),
                str(item["edge_type"]),
                str(item["edge_id"]),
            )
        )

    seed_node_ids = _collect_seed_node_ids(
        resolved_triggers=resolved_triggers, node_map=node_map
    )
    paths: list[dict[str, object]] = []
    depth_clipped = False
    path_count_clipped = False
    for seed_node_id in seed_node_ids:
        if len(paths) >= path_limit:
            path_count_clipped = True
            break
        queue: deque[tuple[list[str], list[str]]] = deque([([seed_node_id], [])])
        min_depth_by_node: dict[str, int] = {seed_node_id: 0}
        while queue:
            node_path_ids, edge_path_ids = queue.popleft()
            current_node_id = node_path_ids[-1]
            current_depth = len(edge_path_ids)
            if current_depth >= depth_limit:
                if adjacency.get(current_node_id):
                    depth_clipped = True
                continue
            for edge in adjacency.get(current_node_id, []):
                next_node_id = str(edge["target_node_id"])
                if next_node_id in node_path_ids:
                    continue
                next_depth = current_depth + 1
                recorded_depth = min_depth_by_node.get(next_node_id)
                if recorded_depth is not None and recorded_depth < next_depth:
                    continue
                min_depth_by_node[next_node_id] = next_depth
                next_node_path_ids = [*node_path_ids, next_node_id]
                next_edge_path_ids = [*edge_path_ids, str(edge["edge_id"])]
                paths.append(
                    _build_path_payload(
                        seed_node_id=seed_node_id,
                        node_path_ids=next_node_path_ids,
                        edge_path_ids=next_edge_path_ids,
                        node_map=node_map,
                        edge_by_id=edge_by_id,
                    )
                )
                if len(paths) >= path_limit:
                    path_count_clipped = True
                    break
                queue.append((next_node_path_ids, next_edge_path_ids))
            if path_count_clipped:
                break
        if path_count_clipped:
            break

    return {
        "seed_node_ids": seed_node_ids,
        "max_depth": depth_limit,
        "max_paths": path_limit,
        "path_count": len(paths),
        "depth_clipped": depth_clipped,
        "path_count_clipped": path_count_clipped,
        "paths": paths,
    }


def _collect_seed_node_ids(
    *,
    resolved_triggers: list[dict[str, object]],
    node_map: dict[str, dict[str, object]],
) -> list[str]:
    candidates: list[str] = []
    for trigger in resolved_triggers:
        object_ref_type = str(trigger.get("object_ref_type", "")).strip()
        object_ref_id = str(trigger.get("object_ref_id", "")).strip()
        if object_ref_type == "graph_node" and object_ref_id in node_map:
            candidates.append(object_ref_id)
        trace_refs = trigger.get("trace_refs")
        if isinstance(trace_refs, dict):
            route_node_ids = trace_refs.get("route_node_ids")
            if isinstance(route_node_ids, list):
                for route_node_id in route_node_ids:
                    node_id = str(route_node_id).strip()
                    if node_id and node_id in node_map:
                        candidates.append(node_id)
        related_object_ids = trigger.get("related_object_ids")
        if isinstance(related_object_ids, list):
            for related in related_object_ids:
                if not isinstance(related, dict):
                    continue
                if str(related.get("object_type", "")).strip() != "graph_node":
                    continue
                node_id = str(related.get("object_id", "")).strip()
                if node_id and node_id in node_map:
                    candidates.append(node_id)
    unique_node_ids: list[str] = []
    seen: set[str] = set()
    for node_id in candidates:
        if node_id in seen:
            continue
        seen.add(node_id)
        unique_node_ids.append(node_id)
    return unique_node_ids


def _build_path_payload(
    *,
    seed_node_id: str,
    node_path_ids: list[str],
    edge_path_ids: list[str],
    node_map: dict[str, dict[str, object]],
    edge_by_id: dict[str, dict[str, object]],
) -> dict[str, object]:
    return {
        "seed_node_id": seed_node_id,
        "depth": len(edge_path_ids),
        "node_ids": node_path_ids,
        "edge_ids": edge_path_ids,
        "nodes": [_serialize_node(node_map[node_id]) for node_id in node_path_ids],
        "edges": [
            _serialize_edge(edge_by_id[edge_id])
            for edge_id in edge_path_ids
            if edge_id in edge_by_id
        ],
    }


def _serialize_node(node: dict[str, object]) -> dict[str, object]:
    return {
        "node_id": str(node.get("node_id", "")),
        "node_type": str(node.get("node_type", "")),
        "short_label": str(node.get("short_label", "")),
        "object_ref_type": str(node.get("object_ref_type", "")),
        "object_ref_id": str(node.get("object_ref_id", "")),
        "status": str(node.get("status", "")),
    }


def _serialize_edge(edge: dict[str, object]) -> dict[str, object]:
    return {
        "edge_id": str(edge.get("edge_id", "")),
        "source_node_id": str(edge.get("source_node_id", "")),
        "target_node_id": str(edge.get("target_node_id", "")),
        "edge_type": str(edge.get("edge_type", "")),
        "strength": edge.get("strength"),
        "status": str(edge.get("status", "")),
    }


def build_messages_from_prompt(rendered_prompt: str) -> list[ChatMessage]:
    marker = "\nUSER:\n"
    if marker in rendered_prompt:
        system_part, user_part = rendered_prompt.split(marker, 1)
    else:
        system_part = rendered_prompt
        user_part = rendered_prompt
    system_text = system_part.strip()
    if system_text.startswith("SYSTEM:"):
        system_text = system_text[len("SYSTEM:") :].strip()
    user_text = user_part.strip()
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=system_text),
        ChatMessage(role=MessageRole.USER, content=user_text),
    ]
