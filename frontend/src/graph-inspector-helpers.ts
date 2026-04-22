export interface NormalizedPredictedLink {
  sourceNodeId: string;
  targetNodeId: string;
  predictedEdgeType: string;
  confidence: number;
  pathCount: number;
  raw: Record<string, unknown>;
}

export interface NormalizedGraphInspectorPayloads {
  supportChains: Array<Record<string, unknown>>;
  predictedLinks: NormalizedPredictedLink[];
  deepChains: Array<Record<string, unknown>>;
  report: {
    summary: Record<string, unknown>;
    top_nodes: Array<Record<string, unknown>>;
    risk_nodes: Array<Record<string, unknown>>;
    dangling_nodes: Array<Record<string, unknown>>;
    unvalidated_assumptions: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
}

function asArray(input: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(input)) return [];
  return input.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object');
}

export function normalizeGraphInspectorPayloads(input: any): NormalizedGraphInspectorPayloads {
  const report = input?.report && typeof input.report === 'object' ? input.report : {};
  return {
    supportChains: asArray(input?.supportChains?.support_chains),
    predictedLinks: asArray(input?.predictedLinks?.predicted_links).map((item) => ({
      sourceNodeId: String(item.source_node_id || ''),
      targetNodeId: String(item.target_node_id || ''),
      predictedEdgeType: String(item.predicted_edge_type || ''),
      confidence: Number(item.confidence || 0),
      pathCount: Number(item.path_count || 0),
      raw: item,
    })),
    deepChains: asArray(input?.deepChains?.deep_chains),
    report: {
      ...report,
      summary: report.summary && typeof report.summary === 'object' ? report.summary : {},
      top_nodes: asArray(report.top_nodes),
      risk_nodes: asArray(report.risk_nodes),
      dangling_nodes: asArray(report.dangling_nodes),
      unvalidated_assumptions: asArray(report.unvalidated_assumptions),
    },
  };
}
