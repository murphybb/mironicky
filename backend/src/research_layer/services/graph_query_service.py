from __future__ import annotations

from collections import deque

from research_layer.graph.repository import GraphRepository


class GraphQueryService:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    def _collect_edges_for_nodes(
        self, *, edges: list[dict[str, object]], node_ids: set[str]
    ) -> list[dict[str, object]]:
        selected_edges = [
            edge
            for edge in edges
            if str(edge.get("source_node_id", "")) in node_ids
            and str(edge.get("target_node_id", "")) in node_ids
        ]
        dedup: dict[str, dict[str, object]] = {
            str(edge["edge_id"]): edge for edge in selected_edges
        }
        return list(dedup.values())

    def _expand_with_hops(
        self,
        *,
        seed_node_ids: set[str],
        edges: list[dict[str, object]],
        max_hops: int,
    ) -> set[str]:
        adjacency: dict[str, set[str]] = {}
        for edge in edges:
            source = str(edge["source_node_id"])
            target = str(edge["target_node_id"])
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set()).add(source)
        visited = set(seed_node_ids)
        queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in visited)
        while queue:
            node_id, depth = queue.popleft()
            if depth >= max_hops:
                continue
            for next_node_id in adjacency.get(node_id, set()):
                if next_node_id in visited:
                    continue
                visited.add(next_node_id)
                queue.append((next_node_id, depth + 1))
        return visited

    def _normalize_edge_type_sequence(
        self, edge_type_sequence: list[str] | None
    ) -> list[str]:
        return [
            normalized
            for normalized in (
                str(edge_type).strip() for edge_type in (edge_type_sequence or [])
            )
            if normalized
        ]

    def _build_typed_adjacency(
        self, *, edges: list[dict[str, object]]
    ) -> dict[str, dict[str, list[dict[str, object]]]]:
        adjacency: dict[str, dict[str, list[dict[str, object]]]] = {}
        for edge in edges:
            edge_type = str(edge.get("edge_type", "")).strip()
            source = str(edge.get("source_node_id", "")).strip()
            target = str(edge.get("target_node_id", "")).strip()
            if not edge_type or not source or not target:
                continue
            for current, next_node_id, direction in (
                (source, target, "forward"),
                (target, source, "reverse"),
            ):
                adjacency.setdefault(edge_type, {}).setdefault(current, []).append(
                    {
                        "next_node_id": next_node_id,
                        "direction": direction,
                        "edge": edge,
                    }
                )
        for edge_type in adjacency:
            for node_id in adjacency[edge_type]:
                adjacency[edge_type][node_id] = sorted(
                    adjacency[edge_type][node_id],
                    key=lambda item: (
                        str(item.get("next_node_id", "")),
                        str(item.get("edge", {}).get("edge_id", "")),
                        str(item.get("direction", "")),
                    ),
                )
        return adjacency

    def _traverse_typed_metapath(
        self,
        *,
        start_node_ids: list[str],
        edge_type_sequence: list[str],
        adjacency: dict[str, dict[str, list[dict[str, object]]]],
        max_paths: int,
    ) -> list[dict[str, object]]:
        if not start_node_ids or not edge_type_sequence:
            return []

        states: list[dict[str, object]] = [
            {"path_node_ids": [node_id], "path_edge_ids": [], "steps": []}
            for node_id in sorted(set(start_node_ids))
        ]
        for hop_index, expected_edge_type in enumerate(edge_type_sequence, start=1):
            next_states: list[dict[str, object]] = []
            for state in states:
                path_node_ids = [
                    str(item) for item in state.get("path_node_ids", []) if str(item)
                ]
                path_edge_ids = [
                    str(item) for item in state.get("path_edge_ids", []) if str(item)
                ]
                steps = list(state.get("steps", []))
                if not path_node_ids:
                    continue
                current_node_id = path_node_ids[-1]
                candidates = adjacency.get(expected_edge_type, {}).get(current_node_id, [])
                for candidate in candidates:
                    next_node_id = str(candidate.get("next_node_id", "")).strip()
                    edge = candidate.get("edge", {})
                    edge_id = str(edge.get("edge_id", "")).strip()
                    if not next_node_id or not edge_id:
                        continue
                    if next_node_id in path_node_ids:
                        continue
                    step = {
                        "hop_index": hop_index,
                        "edge_id": edge_id,
                        "edge_type": expected_edge_type,
                        "source_node_id": str(edge.get("source_node_id", "")),
                        "target_node_id": str(edge.get("target_node_id", "")),
                        "direction": str(candidate.get("direction", "")),
                        "strength": round(float(edge.get("strength", 0.0) or 0.0), 6),
                    }
                    next_states.append(
                        {
                            "path_node_ids": path_node_ids + [next_node_id],
                            "path_edge_ids": path_edge_ids + [edge_id],
                            "steps": [*steps, step],
                        }
                    )
            if not next_states:
                states = []
                break
            next_states = sorted(
                next_states,
                key=lambda item: (
                    str(item["path_node_ids"][-1]),
                    ",".join(str(node_id) for node_id in item["path_node_ids"]),
                    ",".join(str(edge_id) for edge_id in item["path_edge_ids"]),
                ),
            )
            if max_paths > 0 and len(next_states) > max_paths * 8:
                next_states = next_states[: max_paths * 8]
            states = next_states

        path_evidence: list[dict[str, object]] = []
        for index, state in enumerate(states, start=1):
            path_node_ids = [str(item) for item in state.get("path_node_ids", [])]
            path_edge_ids = [str(item) for item in state.get("path_edge_ids", [])]
            steps = [step for step in state.get("steps", []) if isinstance(step, dict)]
            strengths = [float(step.get("strength", 0.0) or 0.0) for step in steps]
            path_score = round(sum(strengths) / len(strengths), 6) if strengths else 0.0
            start_node_id = path_node_ids[0] if path_node_ids else ""
            end_node_id = path_node_ids[-1] if path_node_ids else ""
            path_evidence.append(
                {
                    "path_id": f"metapath_{index}",
                    "start_node_id": start_node_id,
                    "end_node_id": end_node_id,
                    "edge_type_sequence": list(edge_type_sequence),
                    "hop_count": len(path_edge_ids),
                    "path_node_ids": path_node_ids,
                    "path_edge_ids": path_edge_ids,
                    "path_score": path_score,
                    "steps": steps,
                    "trace_refs": {
                        "start_node_id": start_node_id,
                        "end_node_id": end_node_id,
                        "path_signature": "->".join(path_node_ids),
                    },
                }
            )
        path_evidence = sorted(
            path_evidence,
            key=lambda item: (
                -float(item.get("path_score", 0.0)),
                str(item.get("start_node_id", "")),
                str(item.get("end_node_id", "")),
                ",".join(str(edge_id) for edge_id in item.get("path_edge_ids", [])),
            ),
        )
        if max_paths > 0:
            path_evidence = path_evidence[:max_paths]
        return path_evidence

    def _collect_nodes_and_edges_for_paths(
        self,
        *,
        nodes: list[dict[str, object]],
        edges: list[dict[str, object]],
        path_evidence: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        selected_node_ids: set[str] = set()
        selected_edge_ids: set[str] = set()
        for path in path_evidence:
            selected_node_ids.update(
                str(node_id) for node_id in path.get("path_node_ids", []) if str(node_id)
            )
            selected_edge_ids.update(
                str(edge_id) for edge_id in path.get("path_edge_ids", []) if str(edge_id)
            )
        node_map = {str(node.get("node_id", "")): node for node in nodes}
        edge_map = {str(edge.get("edge_id", "")): edge for edge in edges}
        selected_nodes = [
            node_map[node_id]
            for node_id in sorted(selected_node_ids)
            if node_id in node_map
        ]
        selected_edges = [
            edge_map[edge_id]
            for edge_id in sorted(selected_edge_ids)
            if edge_id in edge_map
        ]
        return selected_nodes, selected_edges

    def query_subgraph(
        self,
        *,
        workspace_id: str,
        center_node_id: str | None,
        max_hops: int,
    ) -> dict[str, list[dict[str, object]]]:
        nodes = self._repository.list_nodes(workspace_id=workspace_id)
        edges = self._repository.list_edges(workspace_id=workspace_id)
        if center_node_id is None:
            return {"nodes": nodes, "edges": edges}

        node_map = {node["node_id"]: node for node in nodes}
        if center_node_id not in node_map:
            return {"nodes": [], "edges": []}

        visited = self._expand_with_hops(
            seed_node_ids={center_node_id},
            edges=edges,
            max_hops=max_hops,
        )

        selected_nodes = [node_map[node_id] for node_id in visited]
        selected_edges = self._collect_edges_for_nodes(edges=edges, node_ids=visited)
        return {"nodes": selected_nodes, "edges": selected_edges}

    def query_typed_metapath_paths(
        self,
        *,
        workspace_id: str,
        start_node_ids: list[str] | None,
        edge_type_sequence: list[str],
        max_paths: int = 64,
    ) -> dict[str, object]:
        nodes = self._repository.list_nodes(workspace_id=workspace_id)
        edges = self._repository.list_edges(workspace_id=workspace_id)
        node_map = {str(node.get("node_id", "")): node for node in nodes}
        normalized_edge_types = self._normalize_edge_type_sequence(edge_type_sequence)
        normalized_start_ids = sorted(
            {
                str(node_id)
                for node_id in (start_node_ids or list(node_map.keys()))
                if str(node_id) in node_map
            }
        )

        if not normalized_start_ids or not normalized_edge_types:
            return {
                "nodes": [],
                "edges": [],
                "path_evidence": [],
                "trace_refs": {
                    "query_type": "typed_metapath_traversal",
                    "seed_node_ids": normalized_start_ids,
                    "edge_type_sequence": normalized_edge_types,
                    "returned_path_count": 0,
                    "returned_node_ids": [],
                    "returned_edge_ids": [],
                },
            }

        adjacency = self._build_typed_adjacency(edges=edges)
        path_evidence = self._traverse_typed_metapath(
            start_node_ids=normalized_start_ids,
            edge_type_sequence=normalized_edge_types,
            adjacency=adjacency,
            max_paths=max_paths,
        )
        selected_nodes, selected_edges = self._collect_nodes_and_edges_for_paths(
            nodes=nodes,
            edges=edges,
            path_evidence=path_evidence,
        )
        trace_refs = {
            "query_type": "typed_metapath_traversal",
            "seed_node_ids": normalized_start_ids,
            "edge_type_sequence": normalized_edge_types,
            "returned_path_count": len(path_evidence),
            "returned_node_ids": [
                str(node.get("node_id", "")) for node in selected_nodes
            ],
            "returned_edge_ids": [
                str(edge.get("edge_id", "")) for edge in selected_edges
            ],
        }
        return {
            "nodes": selected_nodes,
            "edges": selected_edges,
            "path_evidence": path_evidence,
            "trace_refs": trace_refs,
        }

    def predict_missing_edges(
        self,
        *,
        workspace_id: str,
        start_node_ids: list[str] | None,
        edge_type_sequence: list[str],
        predicted_edge_type: str,
        top_k: int = 20,
        max_paths: int = 128,
    ) -> dict[str, object]:
        normalized_predicted_edge_type = str(predicted_edge_type).strip()
        metapath_result = self.query_typed_metapath_paths(
            workspace_id=workspace_id,
            start_node_ids=start_node_ids,
            edge_type_sequence=edge_type_sequence,
            max_paths=max_paths,
        )
        path_evidence = list(metapath_result.get("path_evidence", []))
        existing_pairs: set[tuple[str, str]] = set()
        for edge in self._repository.list_edges(workspace_id=workspace_id):
            if str(edge.get("edge_type", "")).strip() != normalized_predicted_edge_type:
                continue
            source = str(edge.get("source_node_id", "")).strip()
            target = str(edge.get("target_node_id", "")).strip()
            if not source or not target:
                continue
            existing_pairs.add((source, target))

        grouped_paths: dict[tuple[str, str], list[dict[str, object]]] = {}
        skipped_pairs: set[str] = set()
        for path in path_evidence:
            source = str(path.get("start_node_id", "")).strip()
            target = str(path.get("end_node_id", "")).strip()
            if not source or not target or source == target:
                continue
            if (source, target) in existing_pairs:
                skipped_pairs.add(f"{source}->{target}")
                continue
            grouped_paths.setdefault((source, target), []).append(path)

        predictions: list[dict[str, object]] = []
        for (source, target), supporting_paths in grouped_paths.items():
            path_count = len(supporting_paths)
            mean_path_score = (
                sum(float(path.get("path_score", 0.0) or 0.0) for path in supporting_paths)
                / max(1, path_count)
            )
            confidence = min(0.99, 0.2 + 0.18 * path_count + 0.45 * mean_path_score)
            predictions.append(
                {
                    "source_node_id": source,
                    "target_node_id": target,
                    "predicted_edge_type": normalized_predicted_edge_type,
                    "confidence": round(confidence, 6),
                    "path_count": path_count,
                    "path_evidence": supporting_paths,
                    "trace_refs": {
                        "supporting_path_ids": [
                            str(path.get("path_id", "")) for path in supporting_paths
                        ],
                        "edge_type_sequence": self._normalize_edge_type_sequence(
                            edge_type_sequence
                        ),
                    },
                }
            )
        predictions = sorted(
            predictions,
            key=lambda item: (
                -float(item.get("confidence", 0.0)),
                -int(item.get("path_count", 0)),
                str(item.get("source_node_id", "")),
                str(item.get("target_node_id", "")),
            ),
        )
        if top_k > 0:
            predictions = predictions[:top_k]

        return {
            "predictions": predictions,
            "path_evidence": path_evidence,
            "trace_refs": {
                "query_type": "missing_edge_prediction",
                "predicted_edge_type": normalized_predicted_edge_type,
                "edge_type_sequence": self._normalize_edge_type_sequence(
                    edge_type_sequence
                ),
                "seed_node_ids": list(metapath_result.get("trace_refs", {}).get("seed_node_ids", [])),
                "existing_edge_pairs_skipped": sorted(skipped_pairs),
                "returned_prediction_count": len(predictions),
            },
        }

    def query_logical_subgraph(
        self,
        *,
        workspace_id: str,
        formal_refs: list[dict[str, str]] | None = None,
        seed_node_ids: list[str] | None = None,
        max_hops: int = 1,
        limit_nodes: int = 64,
        edge_type_sequence: list[str] | None = None,
        path_limit: int = 32,
    ) -> dict[str, object]:
        nodes = self._repository.list_nodes(workspace_id=workspace_id)
        edges = self._repository.list_edges(workspace_id=workspace_id)
        node_map = {str(node["node_id"]): node for node in nodes}
        normalized_edge_types = self._normalize_edge_type_sequence(edge_type_sequence)

        matched_ref_map: dict[tuple[str, str], list[str]] = {}
        for ref in formal_refs or []:
            object_type = str(ref.get("object_type", "")).strip()
            object_id = str(ref.get("object_id", "")).strip()
            if not object_type or not object_id:
                continue
            matched = [
                str(node.get("node_id"))
                for node in nodes
                if str(node.get("object_ref_type", "")).strip() == object_type
                and str(node.get("object_ref_id", "")).strip() == object_id
            ]
            if matched:
                matched_ref_map[(object_type, object_id)] = sorted(set(matched))

        logical_seed_ids = {
            node_id
            for node_id in (seed_node_ids or [])
            if str(node_id) in node_map
        }
        for matched_node_ids in matched_ref_map.values():
            logical_seed_ids.update(matched_node_ids)

        if not logical_seed_ids:
            return {
                "nodes": [],
                "edges": [],
                "path_evidence": [],
                "trace_refs": {
                    "seed_node_ids": [],
                    "matched_object_refs": [],
                    "returned_node_ids": [],
                    "returned_edge_ids": [],
                    "metapath_edge_type_sequence": normalized_edge_types,
                    "metapath_path_count": 0,
                },
            }

        expanded_node_ids = self._expand_with_hops(
            seed_node_ids=set(logical_seed_ids),
            edges=edges,
            max_hops=max_hops,
        )
        if limit_nodes > 0 and len(expanded_node_ids) > limit_nodes:
            expanded_node_ids = set(sorted(expanded_node_ids)[:limit_nodes])

        selected_nodes = [
            node_map[node_id] for node_id in sorted(expanded_node_ids) if node_id in node_map
        ]
        selected_edges = self._collect_edges_for_nodes(edges=edges, node_ids=expanded_node_ids)
        path_evidence: list[dict[str, object]] = []
        if normalized_edge_types:
            metapath_result = self.query_typed_metapath_paths(
                workspace_id=workspace_id,
                start_node_ids=sorted(logical_seed_ids),
                edge_type_sequence=normalized_edge_types,
                max_paths=path_limit,
            )
            path_evidence = list(metapath_result.get("path_evidence", []))
        trace_refs = {
            "seed_node_ids": sorted(logical_seed_ids),
            "matched_object_refs": [
                {
                    "object_type": object_type,
                    "object_id": object_id,
                    "node_ids": node_ids,
                }
                for (object_type, object_id), node_ids in sorted(
                    matched_ref_map.items(), key=lambda item: (item[0][0], item[0][1])
                )
            ],
            "returned_node_ids": [str(node.get("node_id", "")) for node in selected_nodes],
            "returned_edge_ids": [
                str(edge.get("edge_id", "")) for edge in selected_edges
            ],
            "metapath_edge_type_sequence": normalized_edge_types,
            "metapath_path_count": len(path_evidence),
        }
        return {
            "nodes": selected_nodes,
            "edges": selected_edges,
            "path_evidence": path_evidence,
            "trace_refs": trace_refs,
        }
