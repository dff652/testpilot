# Development State

## Goal

完成 TestPilot P0：确定运行时，落实动作/结果/知识契约、合成校验和三个项目接入清单，为 P1 提供可审查基线。

## Verified current state

- 初始文档提交：`5c817b4`。P0 实现提交：`58c27f2`。当前在 main 分支；文档审查提交为 `dc0c3af`，本轮完成其后续缺陷修复。
- 三份 JSON Schema 0.1.0、跨字段校验 CLI、合成样例、三个项目动作声明和本仓库 Makefile 已实现。
- 选择 Python 3.12/Linux。当前 Python 3.12.3、Node v20.19.2 的合成子进程探针通过；Node 缺失时 Python 检查也通过。没有速度比较或其他平台验收。
- `.venv` 隔离安装 `jsonschema==4.26.0`，requirements-dev.txt 固定全部六项解析依赖；系统运行时与原项目依赖未改动。
- 三项目文档白名单/知识样本、动作来源 commit/hash、锁需求和结果解析要求已登记。
- 生产 Runner、项目适配器、原生测试基线、知识索引和恢复能力尚未实现/执行。
- 2026-09-07 复审的 R1–R5 已修复并由主代理整合验收，见 [审查与关闭报告](docs/review-unpushed-2026-09-07.md)。结论限定为已知缺陷关闭，不能替代 P1 行为验收。

## Decisions

- CLI 优先，首批 Agent Mail、AI Asset Hub、homelab-doctor。
- Agent Mail 首动作是静态 `versions.check`，不是测试覆盖；`test.fast` 的失败 fallback 暂不作为自动通过门禁。
- Go 接入采用待验证的 JSON/无结果缓存事件流，不能把包级 ok 行伪造成测试计数。
- 知识与证据引用显式带项目归属；解释器入口使用 typed path；结构校验不证明真实文件或记录可信。
- 项目原生文档为事实来源，索引可重建，运行证据单独管理。P0/P1 不调用外部模型或写 AgentMemory。

## Validation

- `make check`：8 个 unittest 测试，65 个 mutation 场景、三类基础样例、三个试点声明及非法顶层类型；本地 Markdown 链接和 diff 检查通过。
- `make probe`：Python/Node literal argv、ready 握手、TERM 超时/KILL、Linux subreaper 回收（含 zombie）、中文路径/hash/JSON 通过。
- `PATH=/nonexistent /usr/bin/python3 scripts/runtime_probe.py`：Node 缺失场景通过。
- `.venv/bin/python -m pip check`：通过。
- 定向源检查：15 个白名单文档路径及三份源文件 SHA-256 一致。
- 主代理审查两个 worker 的修复，独立验证 2,048 组计数补全和 32 组解释器入口/参数组合，均通过；非 UTF-8 环境探针、中文链接及 Node 缺失回归通过。旧版本对照能触发新增回归失败。
- P0 实现提交时 `git diff --cached --check` 与暂存敏感内容扫描通过，提交范围限定本项目 26 个文件。没有执行任何原项目测试、生产操作或外部知识写入。

## Next action

已关闭本轮审查缺陷；下一步进入 P1：实现 fixture Runner、注册表与资源锁，再接 Agent Mail 第一个适配器。按 [P0 验收边界](docs/p0-acceptance.md) 分配文件所有权并验证错误路径，之后扩展 Go/Shell 与知识索引。

## External state

未配置远端、未 push、未部署。**用户要求本项目后续 push 统一手动执行；代理仅准备本地提交，禁止执行 push 或等效远端 Git 上传。** 许可证与公开名称尚未确定，不阻塞本地开发。
