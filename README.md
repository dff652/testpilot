# TestPilot

跨项目测试、Bug 分析、日志排查与知识沉淀工作台。

**当前阶段：P1 Runner 与首个适配器。** 已提供三份 Schema、离线校验、登记/执行/取消/恢复 CLI，以及 Agent Mail `versions.check` 适配器；Go/Shell 适配器、知识索引和完整产品验收尚未完成。TestPilot 是工作名，与 GitHub TestPilot、TestPilotAI 或文章中的 Testilot 无从属关系。

## 要解决的问题

多个项目已有原生测试工具、事故文档和验收流程，但缺少统一的项目入口、运行证据和知识关联。TestPilot 负责组织这些资产，通过项目适配器调用既有工具；项目继续拥有业务断言与验收标准。

第一版围绕三个问题工作：

- 这个项目该运行哪些已登记的检查？
- 这次失败有什么直接证据、相似历史问题和下一步验证动作？
- 已验证的修复如何关联回归用例并沉淀为可追溯的经验？

## 已确定的范围

- CLI 优先，先验证协议与执行闭环，再考虑 Web 和 MCP 入口。
- 首批接入 Agent Mail、AI Asset Hub、homelab-doctor；TS Platform 在第二批处理外部服务和设备约束。
- 统一动作、结果、知识三类契约，按项目适配执行环境和退出码语义。
- 项目文档保留在所属仓库；中央索引可重建；运行证据单独保存。
- AI 提议与真实执行结果分开。未经验证的根因只记为假设。
- 首版不包含自动修改生产环境、自动修复循环、全量日志接入或多平台远程调度。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [调研结论](docs/research.md) | 原文章核查、开源候选和证据边界 |
| [本地项目盘点](docs/project-inventory.md) | 六个样本项目、真实入口及适配约束 |
| [架构决策](docs/architecture.md) | 组件职责、知识归属和分阶段范围 |
| [数据契约](docs/contracts.md) | 动作、结果、知识的数据语义与 Schema |
| [试点动作](docs/pilot-actions.md) | 三项目原生动作与知识样本 |
| [P1 CLI 与验收](docs/p1-runner.md) | 登记动作、运行证据、锁与恢复、隔离原生对照 |
| [运行时决策](docs/runtime-decision.md) | 可重复 fixture 实验与技术栈选择 |
| [P0 验收边界](docs/p0-acceptance.md) | 数据、存储、资源决定及后续工作包 |
| [开发前准备](docs/preparation.md) | 待解决事项、验收数据和开始开发的条件 |
| [任务与验收](docs/implementation-plan.md) | 主代理与 luna-worker 分工、里程碑 |
| [开发状态](DEV_STATE.md) | 当前事实、验证范围与下一步 |
| [本地提交审查](docs/review-unpushed-2026-09-07.md) | 审查范围、发现、验证及待修复项 |

## 当前使用方式

先建立隔离开发环境，再执行本仓库的离线检查：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make check
.venv/bin/python scripts/testpilot.py --help
# 单独运行探针；Node 可选，缺失时仍验证 Python
make probe
# 校验一个合成结果，不执行其中声明的动作
.venv/bin/python scripts/validate_contracts.py result examples/valid/result.json
```

首次安装依赖需要包源；后续 check/probe 使用本地 fixture，不执行原项目测试。正式支持范围和已验证平台见运行时决策。原项目命令只是接入清单，执行前仍需检查其资源、副作用及当前项目规则。

尚未配置远端或选择发行许可证；创建本地仓库不表示已经公开发布或授权他人复用代码。P1 已完成隔离 fixture 与 Agent Mail 副本对照；实际原 checkout 的动作范围需由调用者明确选择。

**协作约定：后续 push 统一由用户手动执行。** 代理负责本地开发、验证与提交，不执行 push 或等效远端 Git 上传。
