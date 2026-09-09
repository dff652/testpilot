# 三类数据契约 0.1.0

日期：2026-09-07。P0 已提供 [Action Schema](../contracts/action.schema.json)、[Result Schema](../contracts/result.schema.json)、[Knowledge Schema](../contracts/knowledge.schema.json) 和离线跨字段校验器。`make check` 同时检查 Schema 与 [合成样例](../examples/README.md)。这些格式为首个适配器提供接口基线，不是已实现的生产协议。

借鉴 Agent Mail 的 `contracts/dev-sop/actions.json`、`result.schema.json` 和 `scripts/dev_sop.py`，先做适配再决定哪些设计应提炼。不得把单仓库路径、锁和保留策略直接推广到所有项目。

## 动作 Action

| 字段组 | 0.1.0 当前字段与语义 |
| --- | --- |
| 身份 | `schema_version`, `project_id`, `action_id`, `adapter_id`, `kind` |
| 执行 | 注册的 executable、typed argv（literal/path）、相对工作根目录；0.1.0 不接受动态参数、自由环境变量或 shell 文本 |
| 行为 | `policy.effect/network/secrets/platforms/prerequisites`；secrets 当前只允许 forbidden |
| 资源 | `policy.timeout_seconds/locks`；取消与清理已由 P1 Runner 实现 |
| 证据 | `acceptance.parser/required_artifacts/require_test_counts`；Agent Mail 退出码映射已实现，Go/Shell 待后续 |
| 来源 | `source.path/commit/sha256` |

argv 每项为 `{type: literal|path, value: ...}`。解释器入口文件必须是第一项 typed path，且不得以 `-` 开头；入口之后的 literal 参数按脚本参数处理，允许字面的 `-c` 或 `--eval`。首版不支持入口之前的解释器选项；P1 Runner 已按工作根目录解析 path、核验归属并构造真实 argv，literal 保持原值且不经 shell。文件访问权限不能仅凭参数类型证明，还须校验注册动作、符号链接与工具实际参数语义。

参数需做类型、长度、枚举和路径范围校验。当前不支持凭据注入。后续如增加凭据引用，也不得进入参数序列化、日志或结果。即使名字包含 test/doctor，也不能假设动作没有写入副作用。

## 结果 RunResult

| 字段组 | 0.1.0 当前字段与语义 |
| --- | --- |
| 身份 | `schema_version`, `run_id`, `attempt_id`, `project_id`, `checkout_id`, `action_id` |
| 来源 | commit、dirty 状态、被测内容摘要、动作版本、工具链及环境摘要 |
| 运行 | 开始/结束时间、持续时间、退出码/信号、取消/超时原因 |
| 统计 | 已发现/已执行/通过/失败/跳过数量；缺失为 unknown，不伪造 0 |
| 证据 | artifacts 的相对 path、sha256、media_type、size_bytes、redacted（当前必须为 true）；missing_artifacts 列表 |
| 解释 | `status/reason`；当前没有 summary、warnings 或 suggested_next 字段 |

建议终态：`passed`, `failed`, `blocked`, `cancelled`, `timed_out`, `runner_error`, `inconclusive`；运行中使用 `queued/running`。与原生 runner 状态需要显式映射，不要求修改上游格式。

`passed` 只表示该动作声明的验收条件满足。测试动作通常需要实际执行证据，零测试或仅跳过应为 `inconclusive`/`blocked`；静态检查等不产生测试计数的动作可依据自身已登记规则成功。测试中的合法预期失败等状态由解析器显式处理。所有 passed 结果在 failed 已知时都要求其为 0；check 可保留未知计数，但必须存在零失败补全，不能用 null 隐藏其他计数已推导出的失败。计数未知不放宽已知事实：校验器检查是否存在非负补全，使 `executed = passed + failed` 和 `discovered = executed + skipped` 同时成立。

示例映射：

- 原生命令退出 0，但约定必需报告缺失：`inconclusive`，不是 passed。
- 缺少依赖服务或不支持的平台：`blocked`，不是产品缺陷已确认。
- 测试断言失败：`failed`，但“根因已确认”仍需额外验证。
- 解析器崩溃：`runner_error`；保留原生退出信息和证据。
- 模型认为修复有效：不会改变任何 RunResult。

## 知识 KnowledgeRecord

| 字段组 | 0.1.0 当前字段与语义 |
| --- | --- |
| 身份与范围 | `schema_version/knowledge_id/project_id/visibility/kind` |
| 来源 | `source.project_id/path/commit/sha256/line_start/line_end` |
| 内容 | `title/content`；症状、根因、验证步骤目前写在 content 中，不是独立字段 |
| 关联 | `evidence` 的 project_id/run_id；`superseded_by` 的 project_id/knowledge_id |
| 可信状态 | `status/reviewer/verified_at/shared_by` |
| 更新 | `updated_at/superseded_by`；删除标记、索引版本和失效原因尚无独立字段 |

evidence 是 `{project_id, run_id}` 列表；superseded_by 是 `{project_id, knowledge_id}` 或 null。跨字段校验拒绝不同项目，P1/P2 加载对应记录时还需核验记录存在、实际归属和 hash，不能只信引用声明。

行号仅用于定位，内容哈希/版本用于识别事实。自动生成内容默认 draft。模型分数不等于验证；跨项目经验须经过显式审核与范围推广。

索引删除与证据删除分开：源文件删除后立即停止作为当前知识检索，历史证据按保留规则处理。导出与恢复必须保持引用完整；不能只备份向量或摘要。

## 版本边界与后续实现

- 当前版本 0.1.0，拒绝未知字段和版本；未来破坏性升级须有迁移样例。
- 产物上限 10 MiB，SHA-256，默认 14 天且显式清理；已引用证据保留规则见 P0 验收边界。
- project/checkout 的注册和移动识别规则。
- 原生错误码、TAP/JUnit/JSON 等格式在首批项目中的实际可用性。
- 进程崩溃后中间状态的恢复、锁租约和跨进程取消协议。

当前版本、大小上限、目录、保留及锁策略见 [P0 验收边界](p0-acceptance.md)。Schema 只校验结构，跨字段算术/项目/时间约束由共享 `src/testpilot/contracts.py` 补充，`scripts/validate_contracts.py` 保留 CLI 兼容入口；运行时还须验证身份、artifact 内容和来源真伪。0.1.0 未加入动态参数、密钥引用、自动迁移与远程锁，不应按表中的未来扩展描述假定它们已支持。

## 当前审查状态

本文件描述数据接口，不等于宣布所有跨字段边界均已覆盖。本轮 R1–R5 已修复，原始反例、关闭证据与范围限制见 [本地提交审查](review-unpushed-2026-09-07.md)。
