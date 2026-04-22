export function getCandidateBulkConfirmDialogCopy(count: number) {
  return {
    title: '确认全部入库',
    body: `这会把 ${count} 条待确认候选直接入图，是否继续？`,
    confirmLabel: '确认入库',
    cancelLabel: '取消',
  };
}
