# P0 首批动作登记

P0 静态核查日期：2026-09-07。2026-09-09 已补充 Agent Mail 首动作的隔离 clone 对照，见 [P1 验收](p1-runner.md)；原 checkout、Go/Shell 动作及项目测试未执行。

本文给主代理实现 Action/RunResult schema 和声明式清单提供输入。命令、退出码和副作用来自当前 checkout 的代码与文档；它们不是本轮运行基线。接入前必须在实际目标 commit 上重新读取并保存一次原生结果。

## 使用约定

项目身份不由本机路径推导。建议把 `project_id` 固定为下表的 slug，把 `checkout_key` 解析为用户配置的 `projects_root` 下的相对目录；可移动 checkout、worktree 或镜像只改变注册表，不改变项目 ID。当前 Action 通过 `project_id` 关联本机注册表并保存相对入口；`checkout_key` 是注册表建议字段，不属于 Action 0.1.0。

| `project_id` | `checkout_key` 建议 | 当前静态快照 commit | P0 动作 |
|---|---|---|---|
| `agent-mail` | `agent-mail` | `97710415187df20b6fa61daa39d8499f3db24e8e` | `versions.check` |
| `ai-asset-hub` | `ai-asset-hub` | `19431e191e10081012b576e5e3c50c531bcadbf2` | `go.test`（需先完成隔离 fixture） |
| `homelab-doctor` | `homelab-doctor` | `b2a70444e6be1670633a86c5ebf8c746c54e3bab` | `make.test` |

适配器执行时的工作目录必须是解析后的 checkout 根目录；先记录 `HEAD`、工作区 dirty 状态和动作定义哈希。文中 argv 数组表示实际子进程命令；声明式 Action 0.1.0 的 argv 使用 `{type: literal|path, value: ...}`，入口文件标为 path。不能把文档或日志内容拼成 shell 命令。

## 统一结果边界

三项动作的原生结果格式不同：Agent Mail 的外层 SOP 已提供 JSON；Go 默认输出包级文本；Shell suite 提供 SUMMARY。适配器应始终保存原始 stdout/stderr、退出码、命令版本、commit、运行环境摘要和解析警告；缺少所需摘要时应为 `inconclusive` 或 `runner_error`，不能仅凭退出码补造测试数量。

`passed` 的含义必须带动作类型：

- `agent-mail/versions.check` 的通过只证明版本声明一致，不是测试通过。
- `ai-asset-hub/go.test` 的通过必须有至少一个实际测试包的成功证据；只有 `[no test files]`、空输出或报告缺失时不能称为测试通过。
- `homelab-doctor/make.test` 的通过只证明 fixture 测试断言通过，不能外推为真实路由器健康。

下文的“结果格式”和“退出码”为 P0 静态代码定义；Agent Mail 首动作的 P1 隔离实测单独记录，不外推到其他动作或原 checkout。

## 1. Agent Mail：`versions.check`

### 动作声明

**TestPilot 调用 argv（推荐）：**

```text
["bash", "scripts/sop.sh", "run", "versions.check", "--json"]
```

工作目录为 `agent-mail` checkout 根目录，无参数。`scripts/sop.sh` 的机器入口和 `versions.check` 示例在 `scripts/sop.sh:4-9,52-58`；动作登记在 `contracts/dev-sop/actions.json:7-18`。

Runner 解包后的原生子进程 argv 是：

```text
["bash", "scripts/sop.sh", "versions"]
```

其构造位置为 `scripts/dev_sop.py:782-787`，`versions` 分发为 `scripts/sop.sh:257-260,324-349`。不要直接调用后一个 argv 作为 TestPilot 入口，否则绕过 Agent Mail 的机器锁、结果文件和脱敏日志。

| 字段 | 静态结论 |
|---|---|
| `action_id` | `versions.check` |
| 原生 effect | `inspect`；脚本只读版本声明 |
| 网络 / secrets | `none` / `forbidden`（动作清单 `actions.json:11-15`） |
| timeout | 60 秒（动作清单 `actions.json:11`） |
| 前置条件 | checkout 中存在 `pyproject.toml`、`src/agent_mail/__init__.py`、`packages/agent-mail/package.json`、`packages/agent-mail/src/version.ts`；可用 `.venv/bin/python` 或 `python3`。检查逻辑见 `scripts/check_versions.py:42-76`。 |
| 真实输入 | Python 的 `pyproject.toml` 与 `__version__`，TypeScript 的 package version、runtime version 和 publish tag；`scripts/check_versions.py:60-81`。 |
| 项目外副作用 | 原生脚本未发现写入。机器 Runner 会在 `.agent-mail/dev-sop/` 创建锁、run 状态、脱敏 stdout/stderr 和 result；还会按最新 25 条/14 天规则清理旧终态记录，见 `scripts/dev_sop.py:32-39,503-540,779-815`。 |
| 资源锁 | `.agent-mail/dev-sop/runner.lock` 的非阻塞独占 `flock`，见 `scripts/dev_sop.py:465-500`。同一 checkout 的所有机器动作应共享 `agent-mail:<checkout>:sop-runner` 锁。 |
| 并发建议 | 默认串行。`release-check-ts` 另会运行 `npm ci` 并替换 workspace 的 `node_modules`，不得与依赖该 workspace 的动作并发；边界见 `docs/guides/DEVELOPMENT-SOP.md:193-197`。这不是本动作的直接副作用，但清单不能把整个 SOP 当成可并行资源。 |

### 原生结果和状态映射

`check_versions.py` 成功返回 0 并打印版本比较和 `[OK] version declarations consistent`；任何不一致累计失败并返回 1，见 `scripts/check_versions.py:78-115`。`sop.sh` 的 `set -euo pipefail` 会传播该退出码。

外层 `run ... --json` 返回 Agent Mail 的 result schema 对象；字段和状态见 `contracts/dev-sop/result.schema.json:7-86`。Runner 当前按子进程退出码映射：0 → `passed`，非零 → `failed`；锁竞争 → `blocked/75`，超时 → `timed_out/124`，取消 → `cancelled/130`，Runner 自身异常 → `runner_error/70`，实现见 `scripts/dev_sop.py:748-771,850-886`。`stdout.log` 和 `stderr.log` 是外层 artifacts，不是版本脚本的业务报告。

TestPilot 不能从这个动作生成 `tests_discovered`、`tests_run` 或 `tests_passed`；它是静态控制检查。非零退出只能说明声明不一致或 Runner 失败，不能直接解释为产品 Bug。

### 文档索引白名单和知识样本

索引只允许以下相对路径，且需记录 commit/内容哈希：

- `docs/guides/DEVELOPMENT-SOP.md`
- `docs/guides/DEVELOPING.md`
- `docs/guides/observability-debugging.md`
- `docs/decisions/decisions.md`

契约 JSON 作为适配器元数据读取，不属于首版 Markdown 索引。

首批知识样本选择 `docs/guides/DEVELOPMENT-SOP.md`（动作、锁、运行记录和人工边界）、`docs/guides/observability-debugging.md`（排障入口）和 `docs/decisions/decisions.md`（决策来源）。`.agent-mail/dev-sop/runs/` 的运行证据单独按保留和脱敏规则归档，不作为普通 Markdown 知识索引；密钥、远程 soak、真实双机和原始生产日志不进入白名单。

### 后续动作：`test.fast`

先登记为 P1，不纳入本轮原生基线。推荐 TestPilot argv：

```text
["bash", "scripts/sop.sh", "run", "test.fast", "--json"]
```

Runner 实际调用 `bash scripts/sop.sh test-fast`；实现是先运行 `pytest -q --ignore=tests/test_m62c_reliability.py -q 2>/dev/null`，失败时再运行完整 `pytest -q`，见 `scripts/sop.sh:116-122`。动作声明为 900 秒、`workspace-write`、loopback、无 secrets，见 `contracts/dev-sop/actions.json:35-46`。

该命令可能生成 pytest 缓存、使用 loopback 或项目测试服务；当前 result runner 只保存尾部文本和退出码，没有测试计数解析。此 fallback 会把前一次失败隐藏在最终退出码后，因此在能够保留两次 attempt、原始失败与摘要之前，`test.fast` 不作为自动通过门禁；后续可评估无 fallback 的 `test.full`。因此必须记录实际 pytest summary、是否触发 fallback、缓存/服务资源，并在摘要缺失、全量为空或仅跳过时标为 `inconclusive`，不能把 `exit 0` 单独升级成回归通过。

## 2. AI Asset Hub：`go.test`

### 动作声明

**原项目基线 argv：**

```text
["go", "test", "./..."]
```

工作目录为 `ai-asset-hub` checkout 根目录。该命令是项目本地门禁的一部分，`docs/development.md:47-63`明确列出 `go test ./...`，完整脚本中的位置为 `scripts/check-local.sh:17-22`。本动作只登记 Go 测试，不把 `check-local.sh` 的 lint、race、vet、安装器和 demo 混入同一结果。

| 字段 | 静态结论 |
|---|---|
| `action_id` | `go.test` |
| effect 建议 | `temp-write`；测试代码普遍写 `t.TempDir()`，Go 还使用构建/测试缓存。若 schema 暂无 `temp-write`，必须用 `workspace-write` 加明细，不能登记为纯 `inspect`。 |
| 网络 | `external-read` 条件性风险：若 module cache 不完整，Go 工具可能下载依赖；需要预置模块或显式离线策略后才可宣称 `none`。 |
| secrets | `forbidden`；不向动作注入凭据。 |
| 前置条件 | Go toolchain、可解析的 `go.mod`、已锁定的依赖和可写临时/Go cache；版本与本机工具链须在运行时记录。项目要求先跑 `dev-doctor.sh`，见 `docs/development.md:18-30`。 |
| 应用服务 | 当前测试源静态检查未发现启动 PostgreSQL、Redis 或监听端口的测试；MCP 测试在进程内调用 handler，见 `internal/mcp/server_test.go:54-125`。这不是运行证明，必须由隔离 fixture 验证。 |
| 真实写入 | 代表性 e2e 测试在 `t.TempDir()` 中 build/apply/rollback，见 `internal/e2e/apply_scan_loop_test.go:15-24,39-49,94-110`；测试自身断言临时树变化，不应触碰真实 HOME。 |
| 外部共享资源 | 默认 `GOCACHE`、`GOMODCACHE`、module download cache 和 Go toolchain 可能跨 checkout 共享；项目没有为该命令提供跨进程锁。适配器应隔离 cache，或对实际 cache locator 加锁。 |

### 开发前必须完成的隔离 fixture

“是否需要服务”目前的结论是：没有发现已登记的应用服务依赖，但尚无实测证据；“是否有副作用”结论是：测试会写临时目录，Go 会使用共享 cache，模块缺失时可能外部读取。启用动作前准备一个只读源 checkout 的 fixture/runner，至少做到：

1. 为 `HOME`、`GOCACHE`、`GOMODCACHE` 指定临时目录，并在运行前后对 checkout、临时目录、子进程和监听 socket 做快照。
2. 在依赖已预置的条件下设置 `GOPROXY=off`、`GOTOOLCHAIN=local`，确认不需要网络和额外服务；依赖未预置应记录为 `blocked`，不要偷偷恢复联网下载。
3. 保存每个包的原始 `go test` 输出，区分编译失败、测试断言失败、无测试文件和模块缺失。
4. 若快照发现真实服务、固定端口或 checkout 写入，提升资源锁和 effect 分级，再决定是否保留 `go.test` 为 P0。

这项 fixture 是开发前准备，不代表本轮已经运行 `go test ./...`。

### 原生结果和“通过”门槛

`go test ./...` 没有项目自定义 JSON/JUnit 输出；Go 标准输出按包显示 `ok`、`FAIL` 或 `[no test files]`，命令退出 0 表示 Go 工具认为所有选中的 package 成功，非零表示构建或测试失败。TestPilot 应保留完整原始输出和 Go 版本，不应只保留最后一行。

P0 声明式清单使用待验证的 `go test -json -count=1 ./...`，保留原项目测试范围，同时获取事件流并关闭成功结果缓存复用。其事件语义见 [Go 官方 test2json 文档](https://pkg.go.dev/cmd/test2json)。P1 按 Package + Test 聚合终态，区分包级事件与测试事件，不重复计算父子用例；计数单位需固定，未完成该解析器时不能判定 passed。

至少同时满足以下条件，才可将该动作映射为 TestPilot `passed`：退出码为 0、输出覆盖预期 package、有可核验的实际测试事件及一致计数、没有 module/download/服务阻断、输出未截断。全是 `[no test files]`、只有编译成功、只看到缓存命中或结果缺失时为 `inconclusive`；依赖/工具链/服务不可用为 `blocked`；测试断言失败为 `failed`。原始包级文本不得凭空转换为测试数量；缺少事件流与计数解析时保持 inconclusive。

### 文档索引白名单和知识样本

索引白名单：

- `README.md`
- `docs/README.md`
- `docs/development.md`
- `docs/runbooks/fake-home-loop.md`
- `docs/troubleshooting/ai-asset-pitfalls.md`
- `docs/decisions/0003-cli-first-go-core-and-product-surfaces.md`
- `docs/decisions/0005-read-only-mcp-server-surface.md`

首批知识样本选择 `docs/development.md`（本地门禁、变异验证和平台边界，尤其 `:32-71,83-96`）、`docs/runbooks/fake-home-loop.md`（临时 fake HOME 的 validate/build/diff/apply/scan/rollback 闭环，`:24-29,61-74`）和 `docs/troubleshooting/ai-asset-pitfalls.md`（常见失败解释）。`README.md:227-231`是开发入口索引。真实 HOME、凭据和外部服务日志不进入 TestPilot 普通索引；fake HOME 结果不能外推为真实机器验收。

## 3. homelab-doctor：`make.test`

### 动作声明

**TestPilot argv：**

```text
["make", "test"]
```

工作目录为 `homelab-doctor` checkout 根目录。Makefile 将它精确映射到 `./tests/test.sh`，见 `Makefile:1-5`；因此不能把 `make check` 登记成同一个动作，后者还包含 ShellCheck 和敏感模式扫描，见 `Makefile:6-13`。

| 字段 | 静态结论 |
|---|---|
| `action_id` | `make.test` |
| effect 建议 | `temp-write`；`tests/test.sh:4-6` 创建临时目录并在退出/中断时清理，当前未发现 checkout 写入。 |
| 网络 / secrets | `none` / `forbidden`。测试把 `ssh` 等命令链接到 `tests/fixtures/stub-command.sh`，不需要真实路由器；构造逻辑见 `tests/test.sh:11-15`。 |
| 前置条件 | POSIX `sh`、`make`、基础 Unix 工具、可执行 `tests/test.sh`、完整 `tests/fixtures/{ok,warn,fail}`。不要求真实 SSH 凭据。 |
| 应用服务 | fixture-only；测试通过 `PATH`、`HD_FIXTURE_PROFILE`、脱敏配置和命令桩模拟远端状态，见 `tests/test.sh:41-67,352-365`。 |
| 真实副作用 | 临时目录、stub symlink、临时配置和输出；`trap` 清理。不要自动生成 `config/*.local.conf`，不要注入真实设备配置。 |
| 资源锁 | 当前源代码没有跨进程锁；默认按 `homelab-doctor:<checkout>:make-test` 串行，至少保护临时目录命名、CPU/进程和同一 checkout。真实设备资源不应由此动作声明或访问。 |

### 原生结果和退出码

`tests/test.sh` 输出逐项 `[OK]`/`[!]`，最后输出 `SUMMARY pass=N fail=M` 并执行 `[ "$fail" -eq 0 ]`，见 `tests/test.sh:415-435`。测试中的 `run_fail` 用于确认故障/非法输入确实失败，预期失败本身计入 pass；不能把其中的 `[!]` 直接当作本轮测试失败。

`make test` 退出 0 只在最终 `fail=0`；Make 或脚本本身错误通常为非零。项目 CLI 的产品诊断状态另有约定：0 表示无 `[!]`（允许 `[WARN]`），1 表示远程诊断故障，2 表示本地配置/用法错误，3 表示 SSH 传输失败，见 `README.md:31-48` 和 `lib/doctor.sh:45-82`。这些产品退出码出现在 fixture 的被测调用中，不应被误读为 `make test` 的 suite 退出码。

TestPilot 只有在完整输出包含末尾 `SUMMARY pass=N fail=0`、外层退出码为 0、且没有输出截断时，才能把 fixture suite 标为 `passed`。当前契约用独立 action_id、parser 和 provenance.environment 明确 fixture 模式（没有 `fixture_mode` 字段），并保留执行环境说明；它不代表家庭网络、路由器或服务真实健康。缺失 SUMMARY、stub/fixture 缺失或 Make 中途失败应为 `runner_error`/`blocked`；测试断言失败应为 `failed`。

### 文档索引白名单和知识样本

索引白名单：

- `README.md`
- `docs/development.md`
- `docs/review-checklist.md`
- `docs/architecture.md`

测试脚本与 fixtures 作为适配器证据单独读取，不属于首版 Markdown 索引。

首批知识样本选择 `README.md`（只读诊断边界和退出码，`:31-48,61-63`）、`docs/development.md`（fixture、命令桩、提交门槛，`:25-34,49-67`）和 `docs/review-checklist.md`（健康/警告/故障输出及 CI/真实设备边界，`:48-88`）。真实家庭拓扑、地址、证书、订阅和原始事故日志明确留在私有基础设施仓库，不能从 TestPilot 自动跨项目共享。

## P0 转入实现前的共同门槛

主代理依据本文生成声明式清单时，应保留以下字段，而不是只保存一行命令：

- 稳定 `project_id`、相对 `checkout_key`、目标 commit 和 dirty 状态；
- argv 数组、工作目录语义、参数白名单、超时、网络和 secrets 边界；
- effect 的真实写入范围、临时目录、共享 cache/服务和锁键；
- 原生 stdout/stderr 格式、退出码、解析器所需的完整摘要和缺失证据处理；
- 文档白名单、知识样本、来源 commit/哈希及当前/过期标记；
- `static_review` 与 `executed` 的 provenance 区分。

本文件完成的是 P0 登记，不是动作通过证明。未经主代理批准、隔离 fixture 和原始结果对照，不运行 `go test ./...`、`make test` 或 `test.fast`，也不把本文的静态结论写入 `verified` 知识状态。
