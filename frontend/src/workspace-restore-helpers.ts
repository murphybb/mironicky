import type { WorkspaceSummaryRecord } from './api';

export interface WorkspaceContentSnapshot {
  sourceCount: number;
  nodeCount: number;
  edgeCount: number;
  routeCount: number;
  candidateCount: number;
}

export function hasWorkspaceContent(snapshot: WorkspaceContentSnapshot): boolean {
  return (
    snapshot.sourceCount > 0 ||
    snapshot.nodeCount > 0 ||
    snapshot.edgeCount > 0 ||
    snapshot.routeCount > 0 ||
    snapshot.candidateCount > 0
  );
}

export function chooseWorkspaceToRestore(
  currentWorkspaceId: string,
  currentSnapshot: WorkspaceContentSnapshot,
  workspaces: WorkspaceSummaryRecord[],
  defaultWorkspaceId: string
): string | null {
  if (currentWorkspaceId !== defaultWorkspaceId) return null;
  if (hasWorkspaceContent(currentSnapshot)) return null;
  const candidate = workspaces.find((workspace) =>
    workspace.workspace_id !== currentWorkspaceId &&
    hasWorkspaceContent({
      sourceCount: workspace.source_count,
      nodeCount: workspace.node_count,
      edgeCount: workspace.edge_count,
      routeCount: workspace.route_count,
      candidateCount: workspace.candidate_count,
    })
  );
  return candidate?.workspace_id || null;
}
