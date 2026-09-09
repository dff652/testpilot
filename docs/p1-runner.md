# P1 Runner 与 Agent Mail 首个适配器

日期：2026-09-09。已实现 Python 3.12/Linux 的登记、执行、状态、取消和恢复 CLI，以及 `agent-mail/versions.check` 适配器。Go/Shell 适配器、知识索引、业务测试覆盖和证据导出恢复尚未完成；本页不表示整个 P1 或首版产品已完成。

## 当前入口

从 TestPilot 仓库运行；开发依赖仍使用现有 `.venv` 和 `requirements-dev.txt`，不需要安装源项目依赖：

```bash
.venv/bin/python scripts/testpilot.py --help
make check
```

CLI 的 registry 必须显式指定。先在本机准备需要接入的 checkout，下面以隔离副本为例：

```bash
.venv/bin/python scripts/testpilot.py register \
  --registry .testpilot/registry.json \
  --checkout-id agent-mail-isolated \
  --project-id agent-mail \
  --checkout /path/to/isolated-agent-mail \
  --adapter agent-mail \
  --tool bash=/usr/bin/bash

.venv/bin/python scripts/testpilot.py run \
  --registry .testpilot/registry.json \
  --checkout-id agent-mail-isolated \
  --action-id versions.check
```

`register` 只读取目标 Git/source/tool 信息并写本地 registry；不会执行登记动作。`run` 才调用原生 SOP，它会在目标 checkout 写入、保留和清理 `.agent-mail/dev-sop` 记录。因此正式 checkout 的运行范围应由调用者明确选择。本轮实际对照在临时本地 clone 中完成，原 checkout 未执行。

同一 checkout ID 不能重新绑定其他根目录或项目，同一个 registry 内不能用另一个 ID 重复登记相同根目录。已有动作更新需要重新提供来源与工具并显式使用 `--replace`；历史运行保存自己的动作快照。`--action path/to/action.json` 可登记合成 fixture 动作，但必须满足当前支持的策略与解析器，不接受任意 shell 文本。

`run` 向 stdout 输出通过 RunResult 0.1.0 校验的 JSON。CLI 退出码为 passed=0、failed/inconclusive/runner_error=1、blocked=2、timed_out=124、cancelled=130；实际命令退出码和信号保留在结果字段中。登记或输入错误返回固定原因和非零退出码，不回显原始输入。

查询和取消都必须给出 checkout、run 和 attempt 身份：

```bash
.venv/bin/python scripts/testpilot.py status \
  --registry .testpilot/registry.json --checkout-id agent-mail-isolated \
  --run-id run.EXAMPLE --attempt-id attempt.EXAMPLE

.venv/bin/python scripts/testpilot.py cancel \
  --registry .testpilot/registry.json --checkout-id agent-mail-isolated \
  --run-id run.EXAMPLE --attempt-id attempt.EXAMPLE

.venv/bin/python scripts/testpilot.py recover \
  --registry .testpilot/registry.json --checkout-id agent-mail-isolated
```

将 EXAMPLE 替换为实际返回的 ID。`cancel` 只写该 attempt 的取消请求，由监督进程处理；终态不会改写。显式提供已有 `--run-id` 可以产生新 attempt，每次都创建不同目录，不覆盖旧结果。恢复不会自动重跑。

## 执行与证据边界

实现分为 [登记与来源](../src/testpilot/registry.py)、[运行生命周期](../src/testpilot/runner/service.py)、[进程监督](../src/testpilot/runner/process.py)、[结果与脱敏](../src/testpilot/runner/results.py) 和 [Agent Mail 适配器](../src/testpilot/adapters/agent_mail.py)。原有离线校验脚本保留兼容入口，共享实现移至 `src/testpilot/contracts.py`，三份 schema 仍为 0.1.0。

- 运行前检查已登记的项目身份、来源 commit/hash、入口及 typed path、工具绝对路径与内容哈希。来源或已固定文件发生漂移即阻断；literal 保持原值，使用 argv 列表执行。
- 记录 HEAD、dirty、被测内容和动作 hash。内容指纹覆盖 tracked 与 nonignored 文件，排除自身 `.testpilot` 证据；不宣称包含 ignored 的依赖缓存、工具链传递依赖或原子文件系统快照。
- 当前只接受 `network=none`、`secrets=forbidden`、`locks=[git-common-dir]`，解析器仅 `fixture-json` 与 `sop-result`。不继承调用者任意环境变量，使用 attempt 内 HOME/TMPDIR、固定系统 PATH 和 UTF-8。
- 这是对已信任、已登记代码的协作式执行控制，**不是操作系统沙箱**。不会阻断恶意程序自行访问网络或任意文件，也不能约束绕过 TestPilot 的外部进程。额外数据库/设备锁、凭据注入和 OS 级隔离仍未实现。
- 公共锁位于实际 Git common-dir 的 `testpilot/runner.lock`，多个 worktree 或 registry 共享同一个锁；竞争立即返回 blocked。监督进程继承并验证锁描述符，持有到子进程清理和结果保存结束。
- 命令运行于独立 session。监督进程作为 Linux subreaper，取消/超时先 TERM、再 KILL，按进程实例发信号并回收后代；fixture 验证了忽略 TERM 以及另建 session 的后代。

默认证据目录为目标 checkout 的 `.testpilot/runs/<run_id>/<attempt_id>/`。新建运行目录为 0700、文件为 0600，不修改已有调用者目录的权限。RunResult 只引用已处理的产物：

| 文件 | 内容与用途 |
| --- | --- |
| `result.json` | 原子保存、经 schema 与跨字段校验的统一结果 |
| `job.json` | 本次登记快照、执行参数与来源，仅本地受限保存 |
| `stdout.raw` / `stderr.raw` | 原始 SOP/fixture 标准流，受限保存，不作为可检索脱敏正文 |
| `raw-manifest.json` | 原始标准流的路径、大小和 SHA-256，不包含原始文本 |
| `report.json` 或 `native-output.log` | 经敏感模式替换的 stdout 派生副本；Agent Mail 对应外层 SOP JSON |
| `stderr.log` | stderr 脱敏副本 |
| `capture.json` | 实际退出码、流量、截断与清理事实 |
| `process.json` / `supervisor.json` | 本机恢复用进程实例身份 |
| `supervisor.log` / `supervisor-error.json` | 监督进程异常诊断；后者仅异常类型和代码位置 |

标准流与派生产物均限制为 10 MiB。超限记录截断并使结果不能 passed；原始与派生内容分别计算 hash。脱敏目前覆盖常见 token/password/API key/Authorization 和私钥模式，不是对任意秘密格式的完备识别；原始证据和 registry 不进 Git，也不上传或写 AgentMemory。

Agent Mail 适配器只解析一次完整的原生 result 0.1，拒绝错误版本/动作/类型、重复键、非终态和退出码矛盾。原生 `summary/warnings/suggested_next` 不控制命令或成功结论；不沿原生 artifact 路径读取其他文件，也不声称保存了内层命令全部日志。`versions.check` 始终为 check，所有测试计数为 unknown。

## 崩溃与恢复

调用 CLI 被 SIGKILL 后，独立监督进程仍持有公共锁，检测调用者实例消失后终止、回收动作后代，并保存 `runner_error/runner.owner_lost`。已测试该路径。

监督进程本身被 SIGKILL 是另一种故障：OS 释放其锁，但公共 active 记录仍在。只有 active 记录所属的 checkout/project/root 才能恢复；共享 common-dir 的其他 checkout 保持阻断，不读取或返回原结果，也不清除原记录。恢复会检查进程实例、原进程组和继承的 attempt 标记；仍有已识别后代或 zombie 时返回 `recovery.live_children`，保留失败记录并阻断后续运行。它不会依据陈旧 PID 擅自发信号。只有残留已消失时才清除 active 记录；没有终态的运行记为 `runner.interrupted`，绝不升级为成功；queued 状态保留未知开始时间，不虚构已经执行。fixture 中显式清理自己创建的进程后验证了恢复，不把该行为称为任意崩溃都自动清理。

14 天保留期仍是后续显式清理的策略；本版本不自动删除 TestPilot 证据，没有导出/导入、索引重建或跨机器恢复命令。原生 SOP 自己的保留规则照常生效。

## 验收证据

`make check` 已通过 41 个测试（包含 65 个契约 mutation 场景）；43 个本地文档链接、编译检查、依赖一致性、暂存 diff 与敏感扫描均通过。合成验收覆盖登记→执行→状态、同 run 的多 attempt、错误参数与来源漂移、越界 symlink、字面 shell 标点、非零/零测试/报告缺失、取消/超时、共享 worktree 锁、调用者及监督进程崩溃、输出截断、环境与脱敏。详情见 `tests/runner`、`tests/adapters` 及既有 65 个契约 mutation 场景。

原生对照基于 Agent Mail `97710415187df20b6fa61daa39d8499f3db24e8e` 的临时本地 clone：

| 证据 | 结果 |
| --- | --- |
| 直接调用 `bash scripts/sop.sh run versions.check --json` | passed / 0 |
| 通过 TestPilot 调用同一动作 | passed / 0，kind=check，counts 全 null |
| 原 checkout 的 Git 状态与原生 SOP 记录元数据 | 调用前后相同 |
| 原项目测试、部署、外部模型调用 | 未执行 |

本地受限证据位于 `.testpilot/acceptance/2026-09-09-agent-mail/`，包含直接输出、包装结果、该次运行产物和 summary。直接结果 SHA-256 为 `672160de1c2218eac2acdbf931f674ec282db5b4acb4f6a6db18802c188df0eb`，包装结果为 `24b324903275dd778b3937991c80510cd6d9564f72a17fc546aab500169c9352`。临时 clone 已删除，副本运行证据仍保留，不把它作为原 checkout 的生产基线。

初轮集成出现过结果保存失败：实现将原始日志列入了只允许 `redacted=true` 的 RunResult，导致完成的进程被错误恢复为 interrupted。已修正为受限原始文件、单独 raw manifest 和脱敏结果引用；相关成功、失败、取消、超时与截断测试复跑通过。独立审查还发现过共享 common-dir 的外部 checkout 能恢复并返回其他项目结果，以及 queued 的 null 开始时间无法恢复；已加入归属守卫与回归，worker 独立复核通过。另修正测试脚本遗漏 checkout 身份，以及“登记时已越界却期待登记成功”的测试前提；没有放宽运行边界。

下一工作包是 Go 与 Shell 的结果解析、资源映射及隔离原生对照；知识索引仍属于 P2。所有 push 继续由用户手动执行。
