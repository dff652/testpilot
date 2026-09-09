# Development State

## Goal

完成 P1 的 fixture Runner、登记/锁/取消/恢复与首个 Agent Mail 适配器，后续扩展 Go/Shell，再进入知识索引。

## Verified current state

- 本轮基线为 P0 修复提交 `e327f39`；此前 R1–R5 已关闭，三份 schema 保持 0.1.0。
- Python 3.12/Linux CLI 已实现 register/run/status/cancel/recover。共享校验器位于 `src/testpilot/contracts.py`，旧脚本保留兼容入口。
- 登记显式绑定 checkout/project/action、来源与入口 hash、工具绝对路径；运行复核漂移，使用 Git common-dir 公共文件锁。
- 独立监督进程持有锁、限量捕获标准流、取消/超时清理后代并持久化结果；调用者崩溃会收尾，监督进程自身硬崩溃时发现残留则阻断恢复。
- 原始日志受限保存，RunResult 仅引用安全元数据/脱敏派生文件；原始与派生 hash 分开，截断不报告 passed。
- Agent Mail 仅接入 versions.check，严格解析 native result 0.1，保持 check 与未知测试计数。
- Go/Shell 适配器、知识索引、跨机器执行、证据导出/导入/清理尚未实现；不把当前阶段称为完整 P1 或产品验收。

## Decisions

- 只接受 network=none、secrets=forbidden 与 git-common-dir 锁；这是可信登记动作的协作控制，不是 OS 沙箱。
- 不继承调用者任意环境变量；动作使用 attempt 内 HOME/TMPDIR。没有修改系统运行时或源项目依赖。
- 同 run 新执行产生独立 attempt，恢复不自动重跑。旧结果不覆盖。
- 首动作是静态 versions.check；test.fast 的失败 fallback 仍不作为自动通过门禁。
- P0/P1 不调用外部模型、不外发资料、不写 AgentMemory。

## Validation

- `make check`：41 个测试通过，包含 65 个契约 mutation 场景；43 个本地文档链接、编译检查和依赖一致性检查通过；本仓库单测/合成进程覆盖正常与错误结果、登记/状态/多 attempt、路径/参数、共享 worktree 锁、取消/超时、崩溃恢复、截断与脱敏。
- 主代理独立验证真实 TERM 抵抗及另建 session 的后代均被回收；caller SIGKILL 后监督进程保存失败并收尾；监督进程 SIGKILL 后保留残留阻断，fixture 显式清理后才恢复。
- Agent Mail `97710415187df20b6fa61daa39d8499f3db24e8e` 临时 clone：直接 SOP 与包装调用均 passed/0；kind=check，counts 全 null。
- 原 Agent Mail checkout 的 Git 状态与 SOP 记录元数据前后相同；没有运行其测试或生产动作。
- 详细证据、初轮失败及修复、适用范围见 [P1 验收](docs/p1-runner.md)。受限原始证据在 `.testpilot/acceptance/2026-09-09-agent-mail/`，不进 Git。

- 暂存 diff 与敏感扫描通过；提交范围限定 34 个相关文件，受限原始证据未暂存。

## Next action

按 [任务计划](docs/implementation-plan.md) 接入 Go 与 Shell 的结果解析和资源映射，分别做隔离原生对照；之后实现 P2 索引及知识闭环。

## External state

未配置远端、未 push、未部署。**后续 push 统一由用户手动执行，代理只准备本地提交。** 许可证、公开名称和远程能力尚未确定。
