# 多项目抽样清单与接入证据

> 调研快照：2026-09-07。本文只记录上一轮抽样和本轮定向复核得到的入口、文档位置、契约和资源边界，不宣称本轮由本文作者运行了这些项目的测试。行号以本快照读取的文件为准；接入前应在目标 commit 上重新确认。

## 1. 快照范围

首批抽样覆盖六个项目/工作区，分别代表 Python/TypeScript 契约与 Runner、Go CLI、真实数据库集成、Shell 诊断和工业 FDC POC。下表的 commit 由主代理在本轮提供；它们用于定位证据，不等于所有项目都处于干净工作区。

| 项目 | 工作区 | 快照 commit | 工作区备注 |
|---|---|---|---|
| Agent Mail | `/home/dff652/my_project/agent-mail` | `97710415187df20b6fa61daa39d8499f3db24e8e` | 以该 commit 的契约和 SOP 为接入基线 |
| AI Asset Hub | `/home/dff652/my_project/ai-asset-hub` | `19431e191e10081012b576e5e3c50c531bcadbf2` | 实际技术栈是 Go；不要按旧资料写成 TypeScript |
| TS Platform | `/home/dff652/my_project/ts-platform` | `e8fa953de2dfdb3e5c2794d250e86608299cfb99` | 测试会使用 PostgreSQL、Redis 和 worktree 资源 |
| homelab | `/home/dff652/my_project/homelab` | `007b3810ea787816743d11056b4b1fbe8459f277` | 跟踪文件有未提交改动；TestPilot 只能只读取证，不能覆盖用户修改 |
| homelab-doctor | `/home/dff652/my_project/homelab-doctor` | `b2a70444e6be1670633a86c5ebf8c746c54e3bab` | Shell CLI，依赖脱敏 fixture 和命令桩 |
| smic-poc/defect_detect | `/home/dff652/my_project/smic-poc/defect_detect` | `c245544f01e6d11417527290c8d3c5fd634a508f` | FDC POC；Oracle、日志和业务字段均需单独授权/确认 |

路径是证据来源的代码定位，不是 TestPilot 的可写目标。适配器应记录目标 commit、相对路径和行号；跨仓库不能把绝对路径写死成产品链接。

## 2. Agent Mail：动作与结果契约样本

**原生入口。** `docs/guides/DEVELOPMENT-SOP.md:181-191`说明 `contracts/dev-sop/actions.json` 登记动作、别名、超时、副作用、网络、密钥、平台、产物、CI/MCP 分期等元数据，并给出 `bash scripts/sop.sh list --json`、`describe`、`run`、`status`、`cancel` 的机器入口（`docs/guides/DEVELOPMENT-SOP.md:183-189`）。统一入口不能绕过这个动作清单任意执行 Shell。

**动作契约。** `contracts/dev-sop/actions.json:1-18`展示了文档版本和动作数组；其中一个动作的 `timeout_seconds`、`effect`、`network`、`secrets`、`platforms`、`artifacts`、`ci_required` 和 `mcp_phase` 字段位于 `contracts/dev-sop/actions.json:7-18`。这组字段可作为 TestPilot action contract 的候选来源，但不能直接假定所有项目都支持同样的 effect 或网络级别。

**结果契约。** `contracts/dev-sop/result.schema.json:7-20`要求 `schema_version`、`run_id`、`action`、`status`、`exit_code`、时间、摘要、警告、stdout/stderr 尾部、产物和 `suggested_next`；状态枚举在 `contracts/dev-sop/result.schema.json:34-43`，明确包含 `running`、`passed`、`failed`、`blocked`、`cancelled`、`timed_out` 和 `runner_error`。TestPilot 应保留这些差异，不能把非零退出码、环境阻塞或超时压成一个“失败”后丢失原因。

**证据与并发。** SOP 说明运行记录写入被 Git 忽略的 `.agent-mail/dev-sop/runs/`，日志脱敏，保留最新 25 个且不超过 14 天；锁路径为 `.agent-mail/dev-sop/runner.lock`（`docs/guides/DEVELOPMENT-SOP.md:191`）。`release-check-ts` 会执行 `npm ci` 并替换 `packages/agent-mail/node_modules`，不得与依赖该 workspace 的契约、Vitest 或其他动作并行；机器 Runner 通过单实例锁串行化（`docs/guides/DEVELOPMENT-SOP.md:193-197`）。实现侧的运行目录、锁路径和保留上限也在 `scripts/dev_sop.py:32-39`。

**知识路径。** 开发流程和动作说明集中在 `docs/guides/DEVELOPMENT-SOP.md`；流程表在 `docs/guides/DEVELOPMENT-SOP.md:206-215`，其中把本地开发、单测/回归、联调、调试和规格/决策分别关联到脚本与文档。TestPilot 索引应保存这些相对路径和目标 commit，而不是复制 SOP 全文。

## 3. AI Asset Hub：Go 本地门禁与假 HOME 闭环

**原生入口。** `scripts/check-local.sh:9-22`是本地完整门禁，依次调用环境诊断、Shell 语法、开发诊断测试、许可证和校验和检查、安装器测试、README 资源检查，以及 `go test ./...`、`go test -race ./...`、`go vet ./...`、gofmt、golangci-lint 和 demo 闭环。项目 README 把 `./scripts/dev-doctor.sh` 和 `./scripts/check-local.sh`列为开发入口（`README.md:227-231`）。项目实际是 Go Core/CLI，不能按旧记录登记为 TypeScript。

**知识路径。** 资产库与目标工具目录的角色、只读扫描到显式 apply 的流程在 `README.md:103-117`；排障边界位于 `docs/troubleshooting/ai-asset-pitfalls.md`。假 HOME runbook 明确把 `validate → build → diff → apply → scan → rollback → scan`作为闭环（`docs/runbooks/fake-home-loop.md:1-7`），并说明临时目录、回滚后的断言和“不读写真实 HOME”（`docs/runbooks/fake-home-loop.md:24-29`）。这类 runbook 是知识索引的优先来源；假 HOME 结果不能自动外推到真实机器（`docs/runbooks/fake-home-loop.md:69-74`）。

**隔离与并发。** demo 脚本在 `mktemp` 下创建独立 `dist`、`fake-home` 和 `fake-project`（`scripts/demo-apply-scan-loop.sh:28-32`），退出时按 `scripts/demo-apply-scan-loop.sh:34-40`清理。抽样证据中没有发现覆盖所有门禁的统一跨进程锁；TestPilot 适配器第一版应按项目串行，并将临时目录路径和清理状态写入证据。只有确认不同动作不会争用构建目录、安装目标或 fake HOME 后，才可开放并行。

## 4. TS Platform：真实 PostgreSQL/Redis 与 worktree 边界

**原生入口。** `docs/handbooks/testing-strategy.md:17-55`把测试分为纯 fixture 契约、真实 PostgreSQL/Redis 的集成 golden path 和前端 smoke；本地推荐用 `bash scripts/ci/run-tests.sh`，并可用 `--unit-only`、`--workers N`、`--serial` 或 `--no-services`（`docs/handbooks/testing-strategy.md:87-104`）。适配器必须传递项目原生参数，不能把纯 unit 和真实服务集成混成同一个等级。

**服务与数据库。** 集成测试使用真实 PostgreSQL 和 Redis，DSN 来自 `TEST_DATABASE_URL`、`TEST_DATABASE_SYNC_URL`，默认串行数据库为 `ts_platform_test`，并行 worker 使用 `ts_platform_test_gwN`，且明确不是 SQLite（`docs/handbooks/testing-strategy.md:31-46`）。这属于测试环境前置条件，不是 TestPilot 可以用空目录伪造的事实。

**并发矩阵。** `--unit-only`默认最多 8 个 xdist worker；每个 worker 使用独立 PostgreSQL 数据库（`docs/handbooks/testing-strategy.md:106-111`），Redis DB 8–15 为并行测试保留区，业务候选环境使用 DB 0/1（`docs/handbooks/testing-strategy.md:112-113`）。外层 `run-tests.sh`持有 git-common-dir 锁，允许一轮内部受控并行，但禁止两个独立 pytest/run-tests 进程同时运行，以免多个 worktree 争用测试资源（`docs/handbooks/testing-strategy.md:114-119`）。TestPilot 必须把 PostgreSQL 数据库、Redis DB、worktree 锁和 services 生命周期登记为资源，而不是只根据 CPU 核数并发。

**知识路径。** 测试层级、服务要求、禁止的 mock 以及新增模块责任以 `docs/handbooks/testing-strategy.md`为准；fixture 和公共资源由 `backend/tests/conftest.py`提供，文档在 `docs/handbooks/testing-strategy.md:152-156`给出定位。测试耗时数据在 `docs/handbooks/testing-strategy.md:121-131`，是历史运行记录，接入时不能当作当前性能承诺。

## 5. homelab：repo-doctor、事故文档与知识资产

**原生入口。** `tools/repo-doctor/README.md:3-11`把 `bash tools/repo-doctor/check.sh`定义为仓库级离线质量入口，声明不访问外网、不启动采集、不修改设备运行态，并列出语法、死链、结构、工具测试、清单一致性和 `git diff --check`等覆盖。实际编排在 `tools/repo-doctor/check.sh:44-57`，包含结构、Markdown 链接、SVG、多个工具测试、清单检查和 diff 检查。

**知识路径。** `knowledge/README.md:1-5`定义个人知识资产目录的角色，`knowledge/README.md:9-20`列出会话交接、架构设计、公众号入库实施/排障和资产分区等文档；其分层架构和当前状态在 `knowledge/README.md:22-40`。仓库级知识入库流程位于 `docs/运维/项目核心使用流程.md:183-205`，要求私密数据审查、dry-run、校验和人工合并。事故复盘、SOP 和设备/网络文档是 homelab 的主要排障知识源，索引时必须保留原文相对路径与时间状态。

**工作区和并发。** `tools/repo-doctor/check.sh:44-56`按顺序运行多个检查；抽样文件中没有一个统一的跨工具锁。TestPilot 应默认单项目串行，且遵循 `tools/repo-doctor/README.md:33-37`描述的只读、忽略文件和暂存边界。尤其 homelab 当前存在未提交跟踪文件，适配器不应自动格式化、暂存、提交或清理工作区。

## 6. homelab-doctor：Shell fixture 与只读诊断

**原生入口。** `Makefile:1-13`定义 `make test`、`make lint`、`make secrets`和组合入口 `make check`；README 在 `README.md:42-48`说明 `make check`使用脱敏 fixture 和命令桩，不依赖真实路由器。开发约束把 `make check`和 `git diff --check`列为本地检查，并要求 fixture 覆盖健康、警告和故障（`docs/development.md:25-34`）。

**知识路径。** 模块边界、fixture 目录、`tests/test.sh`职责以及提交门槛在 `docs/development.md:49-67`；输出状态、SSH 错误和计数要求在 `docs/review-checklist.md:48-57`，自动测试和 CI 要求在 `docs/review-checklist.md:68-78`。真实家庭拓扑、地址和原始日志留在私人 homelab 仓，项目自身只保存通用代码、脱敏测试和公开文档（`README.md:61-63`）。

**隔离与并发。** `tests/test.sh:4-15`为每轮测试创建临时目录和命令桩；`tests/test.sh:41-67`用 fixture profile 验证状态和退出码；`tests/test.sh:70-89`还断言 `doctor router`只建立一次 SSH。抽样证据没有跨进程资源锁，TestPilot 应把该项目标为 fixture-only、默认串行，并禁止在适配器中注入真实设备凭据。

## 7. smic-poc/defect_detect：FDC POC 的入口与阻断证据

**原生入口。** README 给出主程序一次性/循环/测试模式（`README.md:133-145`），独立模块测试在 `README.md:156-166`，统一测试入口为 `python test/run_tests.py`（`README.md:323-330`）。`test/run_tests.py:45-109`按模块和 `python main.py --test`建立测试命令，单个子命令用 30 秒超时（`test/run_tests.py:13-43`），并按列表顺序逐个执行（`test/run_tests.py:82-90`）。

**知识路径。** 当前主入口和项目边界见 `README.md:7-13`；算法流程和设计/实现差异见 `docs/ALGORITHM_BUSINESS_OVERVIEW.md:1-15`、`docs/ALGORITHM_BUSINESS_OVERVIEW.md:100-116`；已确认问题、业务待确认项和验证要求见 `docs/ISSUES_AND_SOLUTIONS.md:1-23`及其处理优先级 `docs/ISSUES_AND_SOLUTIONS.md:107-120`；版本和维护主线边界见 `docs/VERSION_COMPARISON.md:5-22`。

**已知验收风险。** 文档明确记录主检测器在固定阈值前丢失原始 `EPD_*_max`，导致最终标签无法成为异常，且要求能到达 `label = -1`的端到端回归测试（`docs/ISSUES_AND_SOLUTIONS.md:5-23`；`docs/ALGORITHM_BUSINESS_OVERVIEW.md:83-98`）。TestPilot 不能把内部函数测试或“脚本退出 0”当作业务检测通过。

**资源与并发。** README 声明依赖 Oracle 数据库（`README.md:61-65`），日志位置为 `logs/auto_detection.log`（`README.md:312-313`）；启动脚本还用 PID 文件阻止重复服务（`start_fdc.sh:61-73`）。统一测试入口本身串行执行子命令，但没有证明多个工作区共享 Oracle、特征/结果目录和日志时可以并行。因此适配器应默认串行、先使用脱敏/合成数据，任何真实数据库、服务启动或通知动作都需要显式权限和独立资源锁。

## 8. 对统一适配器的共同要求

六个项目的证据说明，TestPilot 的公共层可以统一以下字段：项目 ID、相对入口、动作 ID、参数、超时、网络、密钥、副作用、资源锁、提交、环境、状态、退出码、摘要、日志尾部、产物、来源文档和下一步。但执行细节必须下沉到项目适配器：

- Agent Mail 的 action/result schema 可作为契约参考，但其 Runner 约束不能覆盖 Go、Shell、数据库和真机项目。
- AI Asset Hub 与 homelab-doctor 适合先做离线 fixture 适配器，证据可重复且不会接触生产 HOME 或真实路由器。
- TS Platform 必须把 PostgreSQL、Redis、worktree 和服务编排作为显式资源，禁止只按 worker 数量并发。
- homelab 的知识索引必须保护未提交改动和私密设施信息；事故文章只能引用已标注时间和来源的证据。
- defect_detect 需要把“代码测试通过”和“业务告警可达”分开，并把已知阻断缺陷作为验收门槛。

统一入口第一次运行前，主代理应保存直接运行原生入口的基线并逐字段对比；任何无法确认的服务、设备、数据库、凭据或业务字段都应记录为 `受阻`或“待现场确认”，不得自动标记为通过。
