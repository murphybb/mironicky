# Mironicky PDF 抽取质量重启交接

## 当前安全状态
- 新干净分支：`codex/pdf-extraction-clean-review`
- 新工作区：`C:\Users\murphy\.config\superpowers\worktrees\mironicky-main\codex-pdf-extraction-clean-review`
- 基线提交：`main@41b66d5`（本地 main，尚不等于 GitHub `origin/main`）
- 旧问题现场：`C:\Users\murphy\Desktop\mironicky-main`，分支 `codex/complete-c-plus-claim-memory`，有未提交可疑改动，不要直接合并。

## 要解决的问题
Mironicky 抽取 PDF 后不能只采集 benchmark、作者、URL、表格行等事实噪声，而要稳定产出可追溯的论文论证链：

- 至少 1 个 `central_claim`
- 至少 2 个 `mechanism_step`
- 至少 2 个 `supporting_evidence`
- 至少 1 个 `limitation` / `failure_mode` / `boundary_condition`
- 至少 1 个 `validation_need`
- 每个候选必须有 `source_span`
- 不允许 fallback/degraded 冒充成功
- 不允许把标题/作者/贡献者、GitHub/URL availability、孤立表格数字、已完成 checker/comparator 检查当作有效论证节点

测试 PDF：

- `C:\Users\murphy\Desktop\mironicky论文\2603.15726v1.pdf`
- `C:\Users\murphy\Desktop\mironicky论文\2604.03789v1.pdf`
- `C:\Users\murphy\Desktop\mironicky论文\s41586-023-06734-w.pdf`

## 已经尝试过什么
- 让 reviewer 语义审查旧结果，发现结构测试通过但语义不合格。
- 增加过噪声过滤：URL/GitHub 可用性、孤立数字表格行、把正向贡献误标成 boundary/limitation、把已完成 Comparator/checker 检查误标成 validation_need。
- 增加过显式论文命题提取：中文编号假设、中文结论、英文 abstract 里的 `we propose/present/introduce`。
- 增加过形式化验证协议识别：`0 sorry`、`compiles`、`final checks`、`proof checks` 等。
- 增加过缺失角色时的 repair 阶段，让 LLM 再补缺的链条角色。
- 用 direct worker 跑过三篇 PDF，旧问题现场最终结构门槛曾通过：`63 passed`，三篇 PDF direct worker 均 succeeded。

## 为什么不建议合并旧问题现场
- 最终独立 reviewer 因额度中断，没有完成“三篇 PDF 通读 + 对照节点/链条”的语义放行。
- 旧问题现场有较大 diff，混合了多轮历史改动和运行产物，风险不适合直接进主线。
- 部分规则过于定制化，例如专门匹配 2604 里的 `scaling to harder problems revealed two further challenges`，可能通过样例但泛化不足。
- direct worker 不是完整 API/浏览器闭环；当时后端 API 因 Mongo/27017 不可用无法完成真实 API 验收。

## 踩过的坑
- 不能只看字段计数。旧结果计数看起来完整，但 candidate 可能是作者、GitHub 链接、表格行、完成检查结果。
- 不能把 “Comparator then checks...” 当成 `validation_need`。这是已完成的验证结果，不是“还需要验证什么”。
- PowerShell here-string 会污染中文路径，`mironicky论文` 可能变成 `mironicky??`。真实 PDF 路径最好在 Python 内用 `Path.home() / 'Desktop' / 'mironicky\\u8bba\\u6587' / ...` 构造。
- 后端端口不可访问不一定是抽取代码坏，可能是 Mongo/27017 没起来。必须分清 API 闭环失败和 worker 抽取失败。
- `allow_fallback=False` 下如果链条角色缺失，worker 正确行为应该是 failed，不应该静默补低质候选。
- LLM 输出不稳定，不能靠“某次跑出来了”证明稳定。需要测试锁住角色缺失、噪声误入、source_span、失败行为。

## 下一步建议
1. 在新干净分支先审查旧问题现场 diff，不要照搬。
2. 先写语义验收脚本或测试，覆盖三篇 PDF 的角色门槛、source_span、噪声黑名单、fallback/degraded 禁止项。
3. 对每个失败点先给出“文件 + 行号 + 根因 + 为什么不是环境问题”，再做最小 patch。
4. 优先改通用能力，不要为某一篇 PDF 写硬编码句子。
5. 修复后必须跑三层验证：
   - 抽取相关 pytest
   - 三篇 PDF direct worker
   - 后端可用时再跑真实 API/Playwright 上传闭环
6. 最后必须找独立 reviewer 通读三篇 PDF 并对照候选节点，未通过就不要合并。

## 旧问题现场可参考但不要直接合并的路径
- 旧工作区：`C:\Users\murphy\Desktop\mironicky-main`
- 旧分支：`codex/complete-c-plus-claim-memory`
- 旧 direct worker 结果：`backend/runtime-check/pdf-chain-semantic-filter-v6-direct-all-runtime_pdf_chain_semantic_filter_v6_direct_all_20260427_160653.json`
- 旧 SQLite：`backend/runtime-check/runtime_pdf_chain_semantic_filter_v6_direct_all_20260427_160653.sqlite3`
