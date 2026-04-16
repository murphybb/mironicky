# PR-F Failure Recompute + Version Diff Evidence (2026-04-04)

## 1. Scope
This evidence package covers PR-F only:
1. failure ingest / validation
2. failure impact analysis
3. recompute orchestration
4. persisted graph version diff
5. route impact derived from persisted canonical source
6. explicit failure semantics and no-bypass evidence

## 2. Success Chain Evidence
Workspace: `ws_prf_evidence_success`

Identifiers:
- failure_id: `failure_9a8783f0f5d1`
- job_id: `job_4d6c23630f64`
- new_version_id: `ver_d9ac93af6d52`
- impacted_route_ids: `['route_601820bb63ed']`

### 2.1 Failure -> Recompute -> Diff -> Route Impact
Failure record excerpt:
```python
{'failure_id': 'failure_9a8783f0f5d1', 'workspace_id': 'ws_prf_evidence_success', 'attached_targets': [{'target_type': 'edge', 'target_id': 'edge_b8b9d1d33553'}], 'observed_outcome': 'support relation broke after new run', 'expected_difference': 'support edge should remain active', 'failure_reason': 'dependency broken', 'severity': 'medium', 'reporter': 'evidence_runner', 'created_at': datetime.datetime(2026, 4, 4, 12, 30, 42, 33479, tzinfo=datetime.timezone.utc)}
```

Job excerpt:
```python
{'job_id': 'job_4d6c23630f64', 'job_type': 'failure_recompute', 'status': 'succeeded', 'workspace_id': 'ws_prf_evidence_success', 'request_id': 'req_prf_recompute_success', 'created_at': '2026-04-04T12:30:42.141074Z', 'started_at': '2026-04-04T12:30:42.195110Z', 'finished_at': '2026-04-04T12:30:42.751311Z', 'result_ref': {'resource_type': 'graph_version', 'resource_id': 'ver_d9ac93af6d52'}, 'error': None}
```

Persisted graph version excerpt:
```python
{'version_id': 'ver_d9ac93af6d52', 'workspace_id': 'ws_prf_evidence_success', 'trigger_type': 'recompute', 'change_summary': 'recompute after failure failure_9a8783f0f5d1: evidence recompute', 'diff_payload': {'failure_id': 'failure_9a8783f0f5d1', 'base_version_id': 'ver_87ad1b278f7a', 'new_version_id': 'ver_d9ac93af6d52', 'added': {'nodes': ['node_4c2249a6b870', 'node_7db88f82ae50', 'node_8f828117e14a', 'node_ce84a65b32bd'], 'edges': ['edge_08211d83d3ef', 'edge_54623760e70f', 'edge_5daf7c1e5ba4', 'edge_9b7ef6574789']}, 'weakened': {'nodes': [], 'edges': ['edge_b8b9d1d33553'], 'routes': ['route_601820bb63ed']}, 'invalidated': {'nodes': [], 'edges': [], 'routes': []}, 'branch_changes': {'created_branch_node_ids': ['node_4c2249a6b870', 'node_7db88f82ae50'], 'created_branch_edge_ids': ['edge_08211d83d3ef', 'edge_5daf7c1e5ba4']}, 'route_score_changes': [{'route_id': 'route_601820bb63ed', 'support_score_before': 68.3, 'support_score_after': 66.8, 'risk_score_before': 10.0, 'risk_score_after': 10.0, 'progressability_score_before': 81.2, 'progressability_score_after': 81.2}], 'route_impacts': [{'route_id': 'route_601820bb63ed', 'version_id': 'ver_d9ac93af6d52', 'base_version_id': 'ver_87ad1b278f7a', 'status_before': 'candidate', 'status_after': 'weakened', 'route_edge_ids': ['edge_b8b9d1d33553'], 'impacted_edge_ids': ['edge_b8b9d1d33553'], 'impacted_node_ids': [], 'reason': 'route impact derived from persisted route_edge_ids_json and persisted route/node status changes'}]}, 'created_at': datetime.datetime(2026, 4, 4, 12, 30, 42, 626835, tzinfo=datetime.timezone.utc), 'request_id': 'req_prf_recompute_success'}
```

Diff payload excerpt:
```json
{
  "failure_id": "failure_9a8783f0f5d1",
  "base_version_id": "ver_87ad1b278f7a",
  "new_version_id": "ver_d9ac93af6d52",
  "weakened": {
    "nodes": [],
    "edges": [
      "edge_b8b9d1d33553"
    ],
    "routes": [
      "route_601820bb63ed"
    ]
  },
  "invalidated": {
    "nodes": [],
    "edges": [],
    "routes": []
  },
  "route_score_changes": [
    {
      "route_id": "route_601820bb63ed",
      "support_score_before": 68.3,
      "support_score_after": 66.8,
      "risk_score_before": 10.0,
      "risk_score_after": 10.0,
      "progressability_score_before": 81.2,
      "progressability_score_after": 81.2
    }
  ],
  "route_impacts": [
    {
      "route_id": "route_601820bb63ed",
      "version_id": "ver_d9ac93af6d52",
      "base_version_id": "ver_87ad1b278f7a",
      "status_before": "candidate",
      "status_after": "weakened",
      "route_edge_ids": [
        "edge_b8b9d1d33553"
      ],
      "impacted_edge_ids": [
        "edge_b8b9d1d33553"
      ],
      "impacted_node_ids": [],
      "reason": "route impact derived from persisted route_edge_ids_json and persisted route/node status changes"
    }
  ]
}
```

Persisted route snapshot excerpt:
```python
{'route_id': 'route_601820bb63ed', 'workspace_id': 'ws_prf_evidence_success', 'title': 'Route: Claim: retrieval harms latency. #1', 'summary': 'Route centers on Claim: retrieval harms latency.. Current supports: 2, assumptions: 0, risks: 0. Treat this summary as degraded and verify key nodes before decision.', 'status': 'weakened', 'support_score': 66.8, 'risk_score': 10.0, 'progressability_score': 81.2, 'novelty_level': 'incremental', 'relation_tags': ['slice7_generated'], 'top_factors': [{'factor_name': 'confirmed_evidence_coverage', 'score_dimension': 'support_score', 'normalized_value': 1.0, 'weight': 0.3, 'weighted_contribution': 0.3, 'status': 'computed', 'reason': 'evidence_over_confirmed_objects', 'refs': {'object_ids': ['evi_aa6ed6733571', 'evi_e8af1f5ed33e'], 'node_ids': ['node_fa4892d9b8df', 'node_0e856a83bb41']}, 'metrics': {'evidence_count': 2, 'confirmed_count': 2}, 'explanation': 'confirmed_evidence_coverage computed (evidence_over_confirmed_objects); normalized=1.0000, weighted_contribution=0.3000'}, {'factor_name': 'next_action_clarity', 'score_dimension': 'progressability_score', 'normalized_value': 0.99, 'weight': 0.3, 'weighted_contribution': 0.297, 'status': 'computed', 'reason': 'action_length_tokens_keywords', 'refs': {}, 'metrics': {'action_length': 98, 'token_count': 13, 'keyword_hit': 1.0}, 'explanation': 'next_action_clarity computed (action_length_tokens_keywords); normalized=0.9900, weighted_contribution=0.2970'}, {'factor_name': 'execution_cost_feasibility', 'score_dimension': 'progressability_score', 'normalized_value': 1.0, 'weight': 0.2, 'weighted_contribution': 0.2, 'status': 'computed', 'reason': 'inverse_of_conflict_and_failure_pressure', 'refs': {'node_ids': []}, 'metrics': {'conflict_ratio': 0.0, 'failure_ratio': 0.0}, 'explanation': 'execution_cost_feasibility computed (inverse_of_conflict_and_failure_pressure); normalized=1.0000, weighted_contribution=0.2000'}], 'score_breakdown': {'support_score': {'normalized_score': 0.668229, 'score': 66.8, 'factors': [{'factor_name': 'confirmed_evidence_coverage', 'score_dimension': 'support_score', 'normalized_value': 1.0, 'weight': 0.3, 'weighted_contribution': 0.3, 'status': 'computed', 'reason': 'evidence_over_confirmed_objects', 'refs': {'object_ids': ['evi_aa6ed6733571', 'evi_e8af1f5ed33e'], 'node_ids': ['node_fa4892d9b8df', 'node_0e856a83bb41']}, 'metrics': {'evidence_count': 2, 'confirmed_count': 2}, 'explanation': 'confirmed_evidence_coverage computed (evidence_over_confirmed_objects); normalized=1.0000, weighted_contribution=0.3000'}, {'factor_name': 'evidence_quality', 'score_dimension': 'support_score', 'normalized_value': 0.539583, 'weight': 0.25, 'weighted_contribution': 0.134896, 'status': 'computed', 'reason': 'text_quality_active_ratio_edge_strength', 'refs': {'object_ids': ['evi_aa6ed6733571', 'evi_e8af1f5ed33e'], 'node_ids': ['node_fa4892d9b8df', 'node_0e856a83bb41']}, 'metrics': {'text_quality': 0.2792, 'active_evidence_ratio': 1.0, 'edge_quality': 0.5}, 'explanation': 'evidence_quality computed (text_quality_active_ratio_edge_strength); normalized=0.5396, weighted_contribution=0.1349'}, {'factor_name': 'cross_source_consistency', 'score_dimension': 'support_score', 'normalized_value': 0.666667, 'weight': 0.2, 'weighted_contribution': 0.133333, 'status': 'computed', 'reason': 'distinct_sources_adjusted_by_conflicts', 'refs': {'source_ids': ['src_5022db117505', 'src_6d3766695049'], 'node_ids': ['node_fa4892d9b8df', 'node_0e856a83bb41']}, 'metrics': {'distinct_source_count': 2, 'conflict_ratio': 0.0}, 'explanation': 'cross_source_consistency computed (distinct_sources_adjusted_by_conflicts); normalized=0.6667, weighted_contribution=0.1333'}, {'factor_name': 'validation_backing', 'score_dimension': 'support_score', 'normalized_value': 0.0, 'weight': 0.15, 'weighted_contribution': 0.0, 'status': 'missing_input', 'reason': 'no_validation_objects', 'refs': {'object_ids': [], 'node_ids': []}, 'metrics': {'validation_count': 0, 'evidence_count': 2}, 'explanation': 'validation_backing missing_input (no_validation_objects); normalized=0.0, contribution=0.0'}, {'factor_name': 'traceability_completeness', 'score_dimension': 'support_score', 'normalized_value': 1.0, 'weight': 0.1, 'weighted_contribution': 0.1, 'status': 'computed', 'reason': 'traceable_node_and_edge_ratio', 'refs': {'node_ids': ['node_fa4892d9b8df', 'node_0e856a83bb41'], 'edge_ids': ['edge_b8b9d1d33553']}, 'metrics': {'traced_node_count': 2, 'traced_edge_count': 1, 'total_node_count': 2, 'total_edge_count': 1}, 'explanation': 'traceability_completeness computed (traceable_node_and_edge_ratio); normalized=1.0000, weighted_contribution=0.1000'}]}, 'risk_score': {'normalized_score': 0.1, 'score': 10.0, 'factors': [{'factor_name': 'unresolved_conflict_pressure', 'score_dimension': 'risk_score', 'normalized_value': 0.0, 'weight': 0.3, 'weighted_contribution': 0.0, 'status': 'computed', 'reason': 'conflict_nodes_over_total_nodes', 'refs': {'node_ids': []}, 'metrics': {'conflict_count': 0, 'total_node_count': 2}, 'explanation': 'unresolved_conflict_pressure computed (conflict_nodes_over_total_nodes); normalized=0.0000, weighted_contribution=0.0000'}, {'factor_name': 'failure_pressure', 'score_dimension': 'risk_score', 'normalized_value': 0.0, 'weight': 0.25, 'weighted_contribution': 0.0, 'status': 'computed', 'reason': 'failure_and_failed_nodes_over_total_nodes', 'refs': {'node_ids': []}, 'metrics': {'failure_node_count': 0, 'failed_node_count': 0, 'total_node_count': 2}, 'explanation': 'failure_pressure computed (failure_and_failed_nodes_over_total_nodes); normalized=0.0000, weighted_contribution=0.0000'}, {'factor_name': 'assumption_burden', 'score_dimension': 'risk_score', 'normalized_value': 0.0, 'weight': 0.2, 'weighted_contribution': 0.0, 'status': 'computed', 'reason': 'assumption_pressure_and_density', 'refs': {'node_ids': []}, 'metrics': {'assumption_count': 0, 'evidence_node_count': 2, 'total_node_count': 2}, 'explanation': 'assumption_burden computed (assumption_pressure_and_density); normalized=0.0000, weighted_contribution=0.0000'}, {'factor_name': 'private_dependency_pressure', 'score_dimension': 'risk_score', 'normalized_value': 0.0, 'weight': 0.15, 'weighted_contribution': 0.0, 'status': 'computed', 'reason': 'private_dependency_nodes_over_total_nodes', 'refs': {'node_ids': []}, 'metrics': {'private_dependency_count': 0, 'total_node_count': 2}, 'explanation': 'private_dependency_pressure computed (private_dependency_nodes_over_total_nodes); normalized=0.0000, weighted_contribution=0.0000'}, {'factor_name': 'missing_validation_pressure', 'score_dimension': 'risk_score', 'normalized_value': 1.0, 'weight': 0.1, 'weighted_contribution': 0.1, 'status': 'computed', 'reason': 'missing_validation_over_evidence', 'refs': {'object_ids': [], 'node_ids': []}, 'metrics': {'evidence_count': 2, 'validation_count': 0}, 'explanation': 'missing_validation_pressure computed (missing_validation_over_evidence); normalized=1.0000, weighted_contribution=0.1000'}]}, 'progressability_score': {'normalized_score': 0.81175, 'score': 81.2, 'factors': [{'factor_name': 'next_action_clarity', 'score_dimension': 'progressability_score', 'normalized_value': 0.99, 'weight': 0.3, 'weighted_contribution': 0.297, 'status': 'computed', 'reason': 'action_length_tokens_keywords', 'refs': {}, 'metrics': {'action_length': 98, 'token_count': 13, 'keyword_hit': 1.0}, 'explanation': 'next_action_clarity computed (action_length_tokens_keywords); normalized=0.9900, weighted_contribution=0.2970'}, {'factor_name': 'execution_cost_feasibility', 'score_dimension': 'progressability_score', 'normalized_value': 1.0, 'weight': 0.2, 'weighted_contribution': 0.2, 'status': 'computed', 'reason': 'inverse_of_conflict_and_failure_pressure', 'refs': {'node_ids': []}, 'metrics': {'conflict_ratio': 0.0, 'failure_ratio': 0.0}, 'explanation': 'execution_cost_feasibility computed (inverse_of_conflict_and_failure_pressure); normalized=1.0000, weighted_contribution=0.2000'}, {'factor_name': 'execution_time_feasibility', 'score_dimension': 'progressability_score', 'normalized_value': 0.875, 'weight': 0.15, 'weighted_contribution': 0.13125, 'status': 'computed', 'reason': 'inverse_of_failed_nodes_and_edge_load', 'refs': {'node_ids': []}, 'metrics': {'failed_ratio': 0.0, 'edge_load': 0.25}, 'explanation': 'execution_time_feasibility computed (inverse_of_failed_nodes_and_edge_load); normalized=0.8750, weighted_contribution=0.1313'}, {'factor_name': 'expected_signal_strength', 'score_dimension': 'progressability_score', 'normalized_value': 0.1675, 'weight': 0.2, 'weighted_contribution': 0.0335, 'status': 'computed', 'reason': 'evidence_text_quality_and_validation_ratio', 'refs': {'object_ids': ['evi_aa6ed6733571', 'evi_e8af1f5ed33e']}, 'metrics': {'evidence_text_quality': 0.2792, 'validation_ratio': 0.0}, 'explanation': 'expected_signal_strength computed (evidence_text_quality_and_validation_ratio); normalized=0.1675, weighted_contribution=0.0335'}, {'factor_name': 'dependency_readiness', 'score_dimension': 'progressability_score', 'normalized_value': 1.0, 'weight': 0.15, 'weighted_contribution': 0.15, 'status': 'computed', 'reason': 'inverse_of_blocked_nodes', 'refs': {'node_ids': []}, 'metrics': {'blocked_count': 0, 'total_node_count': 2}, 'explanation': 'dependency_readiness computed (inverse_of_blocked_nodes); normalized=1.0000, weighted_contribution=0.1500'}]}}, 'node_score_breakdown': [{'node_id': 'node_0e856a83bb41', 'node_type': 'evidence', 'status': 'active', 'object_ref_type': 'evidence', 'object_ref_id': 'evi_e8af1f5ed33e', 'support_contribution': 0.334114, 'risk_contribution': 0.0, 'progressability_contribution': 0.0, 'total_contribution': 0.334114, 'factor_contributions': [{'factor_name': 'confirmed_evidence_coverage', 'score_dimension': 'support_score', 'contribution': 0.15}, {'factor_name': 'evidence_quality', 'score_dimension': 'support_score', 'contribution': 0.067448}, {'factor_name': 'cross_source_consistency', 'score_dimension': 'support_score', 'contribution': 0.066667}, {'factor_name': 'traceability_completeness', 'score_dimension': 'support_score', 'contribution': 0.05}]}, {'node_id': 'node_fa4892d9b8df', 'node_type': 'evidence', 'status': 'active', 'object_ref_type': 'evidence', 'object_ref_id': 'evi_aa6ed6733571', 'support_contribution': 0.334114, 'risk_contribution': 0.0, 'progressability_contribution': 0.0, 'total_contribution': 0.334114, 'factor_contributions': [{'factor_name': 'confirmed_evidence_coverage', 'score_dimension': 'support_score', 'contribution': 0.15}, {'factor_name': 'evidence_quality', 'score_dimension': 'support_score', 'contribution': 0.067448}, {'factor_name': 'cross_source_consistency', 'score_dimension': 'support_score', 'contribution': 0.066667}, {'factor_name': 'traceability_completeness', 'score_dimension': 'support_score', 'contribution': 0.05}]}], 'scoring_template_id': 'general_research_v1', 'scored_at': '2026-04-04T12:30:42.550795Z', 'conclusion': 'Claim: retrieval harms latency.', 'key_supports': ['Claim: retrieval harms latency.', 'Claim: retrieval improves precision.'], 'assumptions': [], 'risks': [], 'next_validation_action': 'Validate conclusion node Claim: retrieval harms latency. with an ablation or controlled experiment', 'conclusion_node_id': 'node_0e856a83bb41', 'route_node_ids': ['node_0e856a83bb41', 'node_fa4892d9b8df'], 'route_edge_ids': ['edge_b8b9d1d33553'], 'key_support_node_ids': ['node_0e856a83bb41', 'node_fa4892d9b8df'], 'key_assumption_node_ids': [], 'risk_node_ids': [], 'next_validation_node_id': None, 'version_id': 'ver_d9ac93af6d52', 'summary_generation_mode': 'degraded_fallback', 'provider_backend': 'unknown', 'provider_model': '', 'request_id': 'req_ws_prf_evidence_success_regenerate', 'llm_response_id': '', 'usage': {'prompt_tokens': None, 'completion_tokens': None, 'total_tokens': None}, 'fallback_used': True, 'degraded': True, 'degraded_reason': 'research.llm_timeout', 'key_strengths': [], 'key_risks': [], 'open_questions': [], 'rank': 1}
```

Persisted `route_edge_ids_json` excerpt:
```json
["edge_b8b9d1d33553"]
```

Recompute events excerpt:
```python
[{'event_id': 'event_d5e4ff87f75a', 'event_name': 'recompute_started', 'timestamp': datetime.datetime(2026, 4, 4, 12, 30, 42, 229899, tzinfo=datetime.timezone.utc), 'request_id': 'req_prf_recompute_success', 'job_id': 'job_4d6c23630f64', 'workspace_id': 'ws_prf_evidence_success', 'source_id': None, 'candidate_batch_id': None, 'component': 'recompute_service', 'step': 'recompute', 'status': 'started', 'refs': {'failure_id': 'failure_9a8783f0f5d1', 'base_version_id': 'ver_87ad1b278f7a', 'route_ids': ['route_601820bb63ed']}, 'metrics': {'trigger': 'failure_attach', 'reason': 'evidence recompute', 'affected_node_count': 4, 'affected_edge_count': 1}, 'error': None}, {'event_id': 'event_7d01bcce9602', 'event_name': 'failure_attached', 'timestamp': datetime.datetime(2026, 4, 4, 12, 30, 42, 491418, tzinfo=datetime.timezone.utc), 'request_id': 'req_prf_recompute_success', 'job_id': None, 'workspace_id': 'ws_prf_evidence_success', 'source_id': None, 'candidate_batch_id': None, 'component': 'failure_impact_service', 'step': 'attach', 'status': 'completed', 'refs': {'failure_id': 'failure_9a8783f0f5d1', 'targets': [{'target_type': 'edge', 'target_id': 'edge_b8b9d1d33553'}], 'impact_summary': {'failure_id': 'failure_9a8783f0f5d1', 'weakened_node_ids': [], 'invalidated_node_ids': [], 'weakened_edge_ids': ['edge_b8b9d1d33553'], 'invalidated_edge_ids': [], 'affected_route_ids': ['route_601820bb63ed'], 'created_gap_node_ids': ['node_8f828117e14a', 'node_ce84a65b32bd'], 'created_branch_node_ids': ['node_7db88f82ae50', 'node_4c2249a6b870'], 'created_branch_edge_ids': ['edge_5daf7c1e5ba4', 'edge_08211d83d3ef'], 'gap_node_ids': ['node_8f828117e14a', 'node_ce84a65b32bd'], 'branch_node_ids': ['node_4c2249a6b870', 'node_7db88f82ae50'], 'branch_edge_ids': ['edge_08211d83d3ef', 'edge_5daf7c1e5ba4']}}, 'metrics': {'affected_node_count': 0, 'affected_edge_count': 1, 'affected_route_count': 1, 'gap_count': 2, 'branch_count': 2}, 'error': None}, {'event_id': 'event_416db2d8dad3', 'event_name': 'score_recalculated', 'timestamp': datetime.datetime(2026, 4, 4, 12, 30, 42, 574793, tzinfo=datetime.timezone.utc), 'request_id': 'req_prf_recompute_success', 'job_id': None, 'workspace_id': 'ws_prf_evidence_success', 'source_id': None, 'candidate_batch_id': None, 'component': 'score_service', 'step': 'score_route', 'status': 'completed', 'refs': {'route_id': 'route_601820bb63ed', 'node_ids': ['node_0e856a83bb41', 'node_fa4892d9b8df']}, 'metrics': {'support_score': 66.8, 'risk_score': 10.0, 'progressability_score': 81.2, 'factor_count': 15}, 'error': None}, {'event_id': 'event_73e410dcb92a', 'event_name': 'diff_created', 'timestamp': datetime.datetime(2026, 4, 4, 12, 30, 42, 720267, tzinfo=datetime.timezone.utc), 'request_id': 'req_prf_recompute_success', 'job_id': 'job_4d6c23630f64', 'workspace_id': 'ws_prf_evidence_success', 'source_id': None, 'candidate_batch_id': None, 'component': 'recompute_service', 'step': 'diff', 'status': 'completed', 'refs': {'failure_id': 'failure_9a8783f0f5d1', 'version_id': 'ver_d9ac93af6d52', 'route_ids': ['route_601820bb63ed'], 'impacted_route_ids': ['route_601820bb63ed']}, 'metrics': {'added_node_count': 4, 'weakened_node_count': 0, 'invalidated_node_count': 0, 'branch_change_count': 2}, 'error': None}, {'event_id': 'event_8fa9b6b46c49', 'event_name': 'recompute_completed', 'timestamp': datetime.datetime(2026, 4, 4, 12, 30, 42, 740726, tzinfo=datetime.timezone.utc), 'request_id': 'req_prf_recompute_success', 'job_id': 'job_4d6c23630f64', 'workspace_id': 'ws_prf_evidence_success', 'source_id': None, 'candidate_batch_id': None, 'component': 'recompute_service', 'step': 'recompute', 'status': 'completed', 'refs': {'failure_id': 'failure_9a8783f0f5d1', 'version_id': 'ver_d9ac93af6d52', 'route_ids': ['route_601820bb63ed'], 'impacted_route_ids': ['route_601820bb63ed']}, 'metrics': {'new_version_id': 'ver_d9ac93af6d52', 'route_count_after': 1, 'weakened_node_count': 0, 'weakened_edge_count': 1}, 'error': None}]
```

## 3. Failure Sample Evidence
Workspace: `ws_prf_evidence_failure`

Request chain:
- failure_id: `failure_9d34c99afbc7`
- request_id: `req_prf_recompute_failure`

Failure response excerpt:
- http_status: `409`
- error_code: `research.version_diff_unavailable`
- message: `route impact unavailable due to missing canonical replay source`
- details: `{'route_id': 'route_a07a291f26ae', 'reason': 'missing', 'job_id': 'job_d2e5b1c97c69'}`

Additional explicit failure sample (`failure not found`):

- request: `POST /api/v1/research/routes/recompute`
- payload: `{"workspace_id":"ws_slice8_failure_not_found","failure_id":"failure_missing","reason":"missing failure should fail","async_mode":false}`
- http_status: `404`
- error_code: `research.not_found`
- message: `failure not found`
- verification source: integration test `test_slice8_recompute_failure_not_found_returns_404`

## 4. Persisted Canonical Source Proof
1. Route impact computation consumed persisted route records from SQLite-backed store.
2. `routes.route_edge_ids_json` was treated as canonical replay/diff source.
3. `NULL`, malformed JSON, non-array, and non-string-member route-edge payloads are explicit `research.version_diff_unavailable` failures.
4. No recompute/version diff/route impact result was hand-seeded.

## 5. Commands and Results
Run from repo root `C:\Users\murphy\Desktop\EverMemOS-latest`.

1. Unit:
```powershell
$env:PYTHONPATH='src'; uv run pytest tests/unit/research_layer/test_slice8_failure_loop_services.py -q
```
- result: `4 passed`

2. Integration:
```powershell
$env:PYTHONPATH='src'; uv run pytest tests/integration/research_api/test_slice8_failure_recompute_diff_flow.py -q
```
- result: `13 passed`

3. PR-F e2e:
```powershell
$env:PYTHONPATH='src'; uv run pytest tests/e2e/research_workspace/test_slice12_e2e_closed_loops.py::test_slice12_prf_failure_recompute_diff_route_impact_chain -q
```
- result: `1 passed`

## 6. Required Declarations
1. This slice did not directly call any LLM/provider in PR-F recompute/failure/diff logic.
2. `route_edge_ids_json` was used as canonical replay/diff source.
3. No manual seed was used to fake recompute/version diff/route impact completion.
