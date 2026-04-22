import assert from 'node:assert/strict';
import test from 'node:test';

import { getCandidateBulkConfirmDialogCopy } from './candidate-bulk-actions-helpers.ts';

test('bulk confirm dialog copy includes exact pending count', () => {
  assert.deepEqual(getCandidateBulkConfirmDialogCopy(12), {
    title: '确认全部入库',
    body: '这会把 12 条待确认候选直接入图，是否继续？',
    confirmLabel: '确认入库',
    cancelLabel: '取消',
  });
});
