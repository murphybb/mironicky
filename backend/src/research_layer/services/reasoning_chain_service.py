from __future__ import annotations

from collections import defaultdict
from typing import Callable

from research_layer.graph.repository import GraphRepository


class ReasoningChainService:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    def _map_node_kind(
        self, *, node_type: str, node_id: str, conclusion_node_id: str
    ) -> str:
        normalized_type = str(node_type).strip().lower()
        if node_id == conclusion_node_id or normalized_type == "validation":
            return "conclusion"
        if normalized_type == "assumption":
            return "assumption"
        return "evidence"

    def _path_signature(
        self, *, path_node_ids: list[str], path_edge_ids: list[str]
    ) -> str:
        return f"nodes:{'->'.join(path_node_ids)}|edges:{'->'.join(path_edge_ids)}"

    def _to_deep_chain_response(
        self, chain: dict[str, object], *, fallback_conclusion_node_id: str
    ) -> dict[str, object]:
        payload = chain.get("payload", {})
        payload_dict = payload if isinstance(payload, dict) else {}
        trace_refs = payload_dict.get("trace_refs", {})
        trace_refs_dict = trace_refs if isinstance(trace_refs, dict) else {}
        return {
            "chain_id": str(chain.get("reasoning_chain_id", "")),
            "conclusion_node_id": str(
                trace_refs_dict.get("conclusion_node_id", fallback_conclusion_node_id)
            ),
            "path_node_ids": [
                str(item)
                for item in payload_dict.get("path_node_ids", [])
                if str(item)
            ]
            if isinstance(payload_dict.get("path_node_ids"), list)
            else [],
            "path_edge_ids": [
                str(item)
                for item in payload_dict.get("path_edge_ids", [])
                if str(item)
            ]
            if isinstance(payload_dict.get("path_edge_ids"), list)
            else [],
            "reasoning_steps": [
                dict(item)
                for item in payload_dict.get("reasoning_steps", [])
                if isinstance(item, dict)
            ]
            if isinstance(payload_dict.get("reasoning_steps"), list)
            else [],
            "required_validation": list(payload_dict.get("required_validation", []))
            if isinstance(payload_dict.get("required_validation"), list)
            else [],
            "trace_refs": trace_refs_dict,
        }

    def _find_existing_chain_by_signature(
        self, *, workspace_id: str, path_signature: str
    ) -> dict[str, object] | None:
        chains = self._repository.list_reasoning_chains(
            workspace_id=workspace_id, status="active"
        )
        for chain in chains:
            if str(chain.get("chain_type", "")) != "deep_reasoning_chain":
                continue
            payload = chain.get("payload", {})
            if not isinstance(payload, dict):
                continue
            trace_refs = payload.get("trace_refs", {})
            if not isinstance(trace_refs, dict):
                continue
            if str(trace_refs.get("path_signature", "")) == path_signature:
                return chain
        return None

    def _build_reasoning_steps(
        self,
        *,
        path_node_ids: list[str],
        path_edge_ids: list[str],
        conclusion_node_id: str,
        weakest_step: dict[str, object],
        node_type_map: dict[str, str],
    ) -> list[dict[str, object]]:
        first_node_id = path_node_ids[0] if path_node_ids else ""
        second_node_id = path_node_ids[1] if len(path_node_ids) > 1 else ""
        first_kind = self._map_node_kind(
            node_type=node_type_map.get(first_node_id, ""),
            node_id=first_node_id,
            conclusion_node_id=conclusion_node_id,
        )
        second_kind = self._map_node_kind(
            node_type=node_type_map.get(second_node_id, ""),
            node_id=second_node_id,
            conclusion_node_id=conclusion_node_id,
        )
        weakest_edge_id = str(weakest_step.get("edge_id", "")).strip()
        weakest_summary = str(weakest_step.get("summary", "")).strip()
        steps: list[dict[str, object]] = []
        if first_node_id:
            steps.append(
                {
                    "kind": first_kind,
                    "summary": f"{first_kind} node: {first_node_id}",
                    "node_id": first_node_id,
                }
            )
        if second_node_id:
            steps.append(
                {
                    "kind": second_kind,
                    "summary": f"{second_kind} node: {second_node_id}",
                    "node_id": second_node_id,
                }
            )
        steps.extend(
            [
                {
                    "kind": "intermediate_reasoning",
                    "summary": f"path edges: {', '.join(path_edge_ids)}",
                    "path_edge_ids": list(path_edge_ids),
                },
                {
                    "kind": "conclusion",
                    "summary": f"conclusion node: {conclusion_node_id}",
                    "node_id": conclusion_node_id,
                },
                {
                    "kind": "validation_need",
                    "summary": weakest_summary
                    if weakest_summary
                    else "weakest link requires manual validation",
                    "edge_id": weakest_edge_id,
                },
            ]
        )
        existing_kinds = {str(step.get("kind", "")) for step in steps}
        if "evidence" not in existing_kinds:
            steps.insert(
                0,
                {
                    "kind": "evidence",
                    "summary": "synthetic evidence anchor for chain completeness",
                    "synthetic": True,
                },
            )
            existing_kinds.add("evidence")
        if "assumption" not in existing_kinds:
            steps.append(
                {
                    "kind": "assumption",
                    "summary": "synthetic assumption to mark verification dependency",
                    "synthetic": True,
                }
            )
        return steps

    def build_and_persist_deep_chains(
        self,
        *,
        workspace_id: str,
        conclusion_node_id: str,
        support_chains: list[dict[str, object]],
        max_chains: int,
    ) -> list[dict[str, object]]:
        deep_chains: list[dict[str, object]] = []
        scoped = support_chains[:max_chains] if max_chains > 0 else support_chains
        node_type_map = {
            str(node.get("node_id", "")): str(node.get("node_type", ""))
            for node in self._repository.list_nodes(workspace_id=workspace_id)
        }
        for index, support_chain in enumerate(scoped, start=1):
            path_node_ids = [
                str(item) for item in support_chain.get("path_node_ids", []) if str(item)
            ]
            path_edge_ids = [
                str(item) for item in support_chain.get("path_edge_ids", []) if str(item)
            ]
            path_signature = self._path_signature(
                path_node_ids=path_node_ids,
                path_edge_ids=path_edge_ids,
            )
            existing = self._find_existing_chain_by_signature(
                workspace_id=workspace_id,
                path_signature=path_signature,
            )
            if existing is not None:
                deep_chains.append(
                    self._to_deep_chain_response(
                        existing, fallback_conclusion_node_id=conclusion_node_id
                    )
                )
                continue
            weakest_step = (
                dict(support_chain.get("weakest_step", {}))
                if isinstance(support_chain.get("weakest_step"), dict)
                else {}
            )
            reasoning_steps = self._build_reasoning_steps(
                path_node_ids=path_node_ids,
                path_edge_ids=path_edge_ids,
                conclusion_node_id=conclusion_node_id,
                weakest_step=weakest_step,
                node_type_map=node_type_map,
            )
            required_validation = [
                step
                for step in reasoning_steps
                if str(step.get("kind", "")) == "validation_need"
            ]
            persisted = self._repository.create_reasoning_chain(
                workspace_id=workspace_id,
                chain_type="deep_reasoning_chain",
                title=f"Deep reasoning chain {index}",
                payload={
                    "path_node_ids": path_node_ids,
                    "path_edge_ids": path_edge_ids,
                    "reasoning_steps": reasoning_steps,
                    "required_validation": required_validation,
                    "trace_refs": {
                        "source_chain_id": str(support_chain.get("chain_id", "")),
                        "conclusion_node_id": conclusion_node_id,
                        "path_signature": path_signature,
                    },
                },
                request_id=None,
                status="active",
            )
            deep_chains.append(
                self._to_deep_chain_response(
                    persisted, fallback_conclusion_node_id=conclusion_node_id
                )
            )
        return deep_chains

    def invalidate_intersecting_deep_chains(
        self,
        *,
        workspace_id: str,
        touched_node_ids: set[str],
        touched_edge_ids: set[str],
    ) -> dict[str, list[str]]:
        normalized_touched_node_ids = {
            str(node_id).strip() for node_id in touched_node_ids if str(node_id).strip()
        }
        normalized_touched_edge_ids = {
            str(edge_id).strip() for edge_id in touched_edge_ids if str(edge_id).strip()
        }
        if not normalized_touched_node_ids and not normalized_touched_edge_ids:
            return {"invalidated_chain_ids": [], "invalidated_conclusion_node_ids": []}

        invalidated_chain_ids: list[str] = []
        invalidated_conclusion_node_ids: list[str] = []
        active_chains = self._repository.list_reasoning_chains(
            workspace_id=workspace_id, status="active"
        )
        for chain in active_chains:
            if str(chain.get("chain_type", "")) != "deep_reasoning_chain":
                continue
            payload = chain.get("payload", {})
            payload_dict = payload if isinstance(payload, dict) else {}
            chain_node_ids = {
                str(node_id).strip()
                for node_id in payload_dict.get("path_node_ids", [])
                if str(node_id).strip()
            }
            chain_edge_ids = {
                str(edge_id).strip()
                for edge_id in payload_dict.get("path_edge_ids", [])
                if str(edge_id).strip()
            }
            if not (
                chain_node_ids.intersection(normalized_touched_node_ids)
                or chain_edge_ids.intersection(normalized_touched_edge_ids)
            ):
                continue
            chain_id = str(chain.get("reasoning_chain_id", "")).strip()
            if not chain_id:
                continue
            updated = self._repository.update_reasoning_chain(
                reasoning_chain_id=chain_id,
                status="superseded",
            )
            if updated is None:
                continue
            invalidated_chain_ids.append(chain_id)
            trace_refs = payload_dict.get("trace_refs", {})
            trace_refs_dict = trace_refs if isinstance(trace_refs, dict) else {}
            conclusion_node_id = str(
                trace_refs_dict.get("conclusion_node_id", "")
            ).strip() or (
                str(payload_dict.get("path_node_ids", [])[-1]).strip()
                if isinstance(payload_dict.get("path_node_ids"), list)
                and payload_dict.get("path_node_ids")
                else ""
            )
            if conclusion_node_id:
                invalidated_conclusion_node_ids.append(conclusion_node_id)
        return {
            "invalidated_chain_ids": invalidated_chain_ids,
            "invalidated_conclusion_node_ids": sorted(
                {
                    conclusion_node_id
                    for conclusion_node_id in invalidated_conclusion_node_ids
                    if conclusion_node_id
                }
            ),
        }

    def resume_invalidated_deep_chains(
        self,
        *,
        workspace_id: str,
        invalidated_chain_ids: list[str],
        support_chain_lookup: Callable[[str, int], list[dict[str, object]]],
    ) -> list[str]:
        if not invalidated_chain_ids:
            return []

        requested_rebuilds: dict[str, int] = defaultdict(int)
        for chain_id in invalidated_chain_ids:
            chain = self._repository.get_reasoning_chain(str(chain_id))
            if chain is None:
                continue
            if str(chain.get("chain_type", "")) != "deep_reasoning_chain":
                continue
            payload = chain.get("payload", {})
            payload_dict = payload if isinstance(payload, dict) else {}
            trace_refs = payload_dict.get("trace_refs", {})
            trace_refs_dict = trace_refs if isinstance(trace_refs, dict) else {}
            conclusion_node_id = str(
                trace_refs_dict.get("conclusion_node_id", "")
            ).strip() or (
                str(payload_dict.get("path_node_ids", [])[-1]).strip()
                if isinstance(payload_dict.get("path_node_ids"), list)
                and payload_dict.get("path_node_ids")
                else ""
            )
            if not conclusion_node_id:
                continue
            requested_rebuilds[conclusion_node_id] += 1

        resumed_chain_ids: list[str] = []
        for conclusion_node_id, count in requested_rebuilds.items():
            support_chains = support_chain_lookup(conclusion_node_id, max(1, count))
            rebuilt = self.build_and_persist_deep_chains(
                workspace_id=workspace_id,
                conclusion_node_id=conclusion_node_id,
                support_chains=support_chains,
                max_chains=max(1, count),
            )
            resumed_chain_ids.extend(
                chain_id
                for chain_id in (
                    str(item.get("chain_id", "")).strip() for item in rebuilt
                )
                if chain_id
            )
        return resumed_chain_ids
