# Mironicky Handoff

## 当前状态

- 工作目录：`C:\Users\murphy\.config\superpowers\worktrees\mironicky-main\main-p2-merge-test`
- 分支：本地 `main`，已合入多 Agent 假设系统真实执行链路，尚未 push。
- 关键提交：
  - `2bf8740 chore: 忽略 Hypothesis 测试缓存`
  - `c028159 test: 对齐多 Agent 集成测试契约`
  - `4fc3f77 merge: 合入真实多 Agent 假设执行链路`
  - `e61cba3 feat: 修复多 Agent 假设系统真实执行链路`

## 已完成

- 已把应合入主线的多 Agent 源码和测试合到本地 `main`。
- 已排除运行产物：`.playwright-mcp/`、临时 SQLite、截图、review 临时目录等。
- 已把 `.hypothesis/` 加入 `.gitignore`。这是 Hypothesis 测试库缓存，不是业务数据。
- 已保留 `main` 上另一个 agent 的 EverMemOS / PaperMap 提交，没有全量覆盖。

## 已验证有效

- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_hypothesis_multi_agent_prompt_parity.py -q`
  - 结果：`10 passed`
- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_hypothesis_multi_agent_real_execution.py -q`
  - 结果：`70 passed`
  - 注意：很慢，约 7 分钟。
- `PYTHONPATH=src uv run pytest tests/unit/research_layer/test_slice9_hypothesis_services.py tests/integration/research_api/test_slice9_hypothesis_multi_agent_flow.py -q`
  - 结果：`10 passed`
- `npm run lint` in `frontend`
  - 结果：通过。

## 试过但没成功

- 直接把脏分支 diff patch 到 `main` 失败：两边差了多轮提交，patch 缺 base blob，不能硬贴。
- 整组 pytest 一次性跑会超时：不是卡死，是 `test_hypothesis_multi_agent_real_execution.py` 太慢。以后分组跑。
- Browser Use 没跑成：本机 Node 是 `v22.17.0`，Browser Use 的 node_repl 要求 `>= v22.22.0`。

## 已发现但未修

- 真实 PDF `2406.01465v2.pdf` 的 source import/extract 已经能成功，`/health` 没再被拖死。
- 但 `literature_frontier` 仍会在 Supervisor 阶段 stop：
  - PDF candidates 已确认，并能形成 `trigger_refs`。
  - 但 `evidence_packets` 只来自 `active_retrieval_trace`。
  - 当 `active_retrieval=false` 时，`evidence_packets=[]`。
  - Supervisor 按 no-fabrication 规则停止，没有进入 Generation / Reflection / Ranking / Evolution / MetaReview。
- 根因位置：
  - `backend/src/research_layer/services/hypothesis_service.py`
  - `generate_literature_frontier_pool()`
  - `_build_literature_trigger_refs()`
  - `_run_active_retrieval_trace()`
  - `backend/src/research_layer/services/hypothesis_multi_agent_orchestrator.py:create_pool()`

## 下一步

1. 不要改 prompt 绕过 Supervisor stop。
2. 修数据桥：把 uploaded source 的 confirmed candidates / source spans 构造成 `evidence_packets`。
3. `active_retrieval=false` 时也必须使用用户上传文献证据包；只是不联网补检索。
4. 加回归测试：uploaded candidates -> literature_frontier -> Supervisor sees non-empty evidence_packets -> Generation 被调用。
5. 再用真实 PDF 重跑：import -> extract -> confirm candidates -> literature_frontier。
6. 断言 3-5 个候选假设卡，且有 provenance / reasoning_chain / validation_need。

## 避坑

- 不要把 `trigger_refs` 当成 evidence。Supervisor / Generation 真正看的是 `evidence_packets`。
- 不要把 deterministic fallback 标成完成。LLM/tool 不可用必须 failed/degraded，并保存 transcript。
- 不要合运行目录或测试缓存。
- 不要在脏主工作区直接切分支；继续用 `main-p2-merge-test` 或新 worktree。
