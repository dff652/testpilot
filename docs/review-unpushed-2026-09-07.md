# 本地 P0 提交审查（2026-09-07）

当前状态：R1–R5 已修复并通过主代理整合验收。下文原始发现对应 `58c27f2`，文档审查提交为 `dc0c3af`；修复与验证记录见文末。

## 原始审查范围与结论

审查基线为 `main` 的 `5c817b4`（初始文档）和 `58c27f2`（P0 契约与探针），从根提交检查全部已跟踪内容。审查开始时工作树干净；未配置 remote/upstream，因此无法定义或验证 `origin/main...HEAD` 的精确未推送差集。本报告记录的是当前全部本地提交，不声称已与远端比较。

两位 luna-worker 分别只读审查契约和探针；主代理检查完整提交范围、复现以下问题并更新文档。**既有检查通过，但 P0 仍有未关闭缺陷；先修复 R1–R4，再冻结契约并依赖它推进 P1。** 本轮不修改代码、不执行原项目测试、不 push。后续 push 由用户统一手动执行。

## 原始发现（修复前）

### R1 / P1：typed path 可被解释器当作内联代码选项

位置：`scripts/validate_contracts.py:36–39`、`contracts/action.schema.json` 的 path 定义。Python 仅匹配独立 `-c`，Node 仅匹配独立 eval/print 选项；path 允许以 `-` 开头。

以合法 action 样例为基础，将 executable 设为 `python3`、argv 设为 `[{"type":"path","value":"-cprint(321)"}]`，当前校验返回 `[]`。直接运行该无害 fixture 得到退出码 0、stdout `321`。Node 的 `--eval=console.log(321)` 同样通过并执行。主代理已独立复现两种情况。

这是当前离线校验的禁令绕过；尚无生产 Runner，不能据此声称发生了生产执行。修复需明确解释器入口和选项的边界，拒绝入口 path 的选项形态；回归覆盖 Python 合并选项、Node 长短选项变体及合法脚本参数。P1 仍需校验真实文件、注册身份和符号链接边界。

### R2 / P2：未知计数掩盖已知字段的必然矛盾

位置：`scripts/validate_contracts.py:52–56`。只有全部计数已知才检查等式。

以合法 result 样例为基础，**设置 `kind=check`**，分别替换 counts 为：

```json
{"discovered":2,"executed":3,"passed":3,"failed":0,"skipped":null}
{"discovered":2,"executed":2,"passed":3,"failed":null,"skipped":0}
```

两者当前均返回 `[]`，主代理已复现。第一项已知 executed 超过 discovered，第二项已知 passed 超过 executed，未知非负计数不能消除矛盾。不要用原样 `kind=test,status=passed` 复现：该分支已有更严格的字段约束。

修复验收：完整计数继续检查等式；部分未知时检查已知下界是否可能成立，同时保留合理 unknown 的有效样例。

### R3 / P2：check 结果可同时声明 passed 和已知失败

位置：`contracts/result.schema.json:355–373`，`failed=0` 仅限制 test 分支。

合法 result 改为 `kind=check,status=passed,exit_code=0`，counts 为 `discovered=2,executed=2,passed=1,failed=1,skipped=0`，当前校验返回 `[]`。主代理已复现；两条等式成立，不能靠 R2 的修复解决。

修复验收：明确 check 计数语义，并拒绝 passed 与已知失败共存；未知计数和确实通过的 check 仍可接受。

### R4 / P2：探针和文档检查器依赖未声明的 UTF-8 locale

位置：`scripts/runtime_probe.py:130,197`、`scripts/check_docs.py:15`。子进程 text 模式和部分文件读取使用默认编码。

```bash
LC_ALL=C PYTHONCOERCECLOCALE=0 PYTHONUTF8=0 /usr/bin/python3 scripts/runtime_probe.py
```

主代理复现退出码 1、`overall_status=failed`、`UnicodeEncodeError`。同环境下文档检查器读取中文文档也有默认解码问题。当前通过记录限定为 UTF-8 环境，不能概括为任意 Linux locale。

修复验收：明确 UTF-8 文件与子进程编码策略；普通环境、非 UTF-8 父进程环境及 Node 缺失场景均验证中文路径、参数和 JSON 输出。

### R5 / P3：Markdown 合法链接标题与尖括号目标误报

位置：`scripts/check_docs.py:15`。正则把可选标题或尖括号当成文件名的一部分。

临时目录存在 `docs/target.md` 时，目标 `docs/target.md` 的普通链接 通过，附加 `"title"` 标题的同目标链接 被误报。目标为 `<docs/target file.md>` 的尖括号链接 也有相同问题。主代理复现了标题形式；worker 复现了尖括号形式。当前仓库只使用简单链接，既有文档检查未受影响。

修复验收：存在的带标题、含空格尖括号链接通过，真正不存在的目标仍失败；如只支持 Markdown 子集，需明确限制。可与 R4 同一工作包处理。

## 验证证据与限制

- 主代理在审查基线上运行 `make check`：4 个 unittest 测试组、52 个 mutation 场景通过；24 个本地 Markdown 链接和 diff 检查通过。上述新复现不在既有 mutation 集内，因此既有绿色结果不构成关闭证据。
- 主代理执行 `.venv/bin/python -m pip check` 通过；两个历史提交的 `git show --check` 通过，历史新增内容定向敏感模式扫描未发现命中。
- worker 执行 `make probe` 与 `PATH=/nonexistent /usr/bin/python3 scripts/runtime_probe.py` 通过。主代理独立复现 R1–R4 的上述反例及 R5 的标题误报。
- 主代理核对三份试点声明引用的源文件 SHA-256，与当前相邻项目文件一致；没有执行三个原项目测试。
- 本轮文档修订后 `make check` 通过（4 个测试组、52 个场景、32 个本地链接），暂存 diff 检查及暂存敏感扫描通过。首次文档检查把报告中的链接语法反例也当成链接而失败；改为描述目标与标题后复跑通过，未修改检查器。

## 文档修订与后续所有权

本轮同步 README 的 Node 可选说明、实现计划的 P0 状态、契约字段表及开发状态；运行时结论增加 locale 限制。在 `dc0c3af` 文档提交时，R1–R5 均保持 OPEN；本次后续代码修复与关闭证据见下节。

后续适合拆成两个 luna-worker 工作包，主代理负责整合审查和验证：

| 所有者 | 独占范围 | 交付与验收 |
| --- | --- | --- |
| 契约 worker | `contracts/*.json`、`scripts/validate_contracts.py`、`tests/contract-cases.json`、`tests/test_contracts.py` | 修复 R1–R3；补充能在旧实现失败的反例、合理 unknown 和合法脚本参数回归 |
| 工具 worker | `scripts/runtime_probe.py`、`scripts/check_docs.py`，新增对应独立测试文件 | 修复 R4–R5；复现非 UTF-8 locale、Node 缺失和 Markdown 有效/无效目标 |
| 主代理 | 文档、合并后的完整 diff 和最终验收 | 审查安全边界及计数语义，运行 `make check`、必要探针和新反例；核对 staged 范围、敏感扫描及提交后状态 |

以上是后续修复分工，当前完成的是只读审查分工。worker 不改对方所有文件、不覆盖已有改动、不各自修改共享文档、不 push；若需要共享路径，由主代理统一调整所有权。先完成这一轮小范围修复，再按 [P0/P1 工作包](p0-acceptance.md) 推进 Runner 和适配器。


## 后续修复与关闭验收

用户确认后，两位 luna-worker 按上述所有权分别实施，主代理审查完整 diff、补充组合反例并独立验收。R1–R5 均为 CLOSED：

| 问题 | 修复 | 关闭证据 |
| --- | --- | --- |
| R1 | 解释器第一项必须为非选项的 typed path；后续 literal 按脚本参数处理 | 合并选项和模块入口反例拒绝；主代理 Python/Node/bash/sh 共 32 项入口与合法参数检查通过 |
| R2 | 将已知计数转化为 executed 的可行区间，检查两个等式是否有非负整数补全 | 新增跨等式 unknown 反例；主代理独立补全枚举 2,048 组合，0 差异 |
| R3 | Schema 约束 passed 的已知 failed 为 0；跨字段校验还要求存在零失败补全 | 已知失败和通过其他计数推导出的失败均拒绝；合理 unknown 仍通过 |
| R4 | 文件与子进程显式 UTF-8；两个 CLI 在非 UTF-8 环境下仅重启自身以启用 UTF-8 | C locale 下探针通过，Node 存在/缺失通过；中文链接目标子进程回归通过 |
| R5 | 提取 inline 链接目标时分离标题与尖括号 | 标题、空格目标通过，缺失目标仍拒绝 |

整合验证：

- 主代理 `make check`：8 个 unittest 测试通过，其中契约 corpus 为 65 个 mutation 场景；文档链接与 diff 检查通过。
- 主代理 `make probe`、非 UTF-8 父环境探针（Node 存在）、同环境 `check_docs.py` 通过；`make check` 包含非 UTF-8 与 Node 缺失的真实子进程回归，均带测试超时保护。
- 主代理计数枚举：状态 passed/failed，各对五个字段取 null/0/1/2 的 1,024 个组合，用独立非负补全作为预期，合计 2,048 个组合无差异。这是有限域验证，不是所有整数的形式证明。
- 契约 worker 在临时目录用旧实现运行新增 corpus，出现 10 项预期差异（9 项错误放行、1 项合法参数误拒），新实现通过。主代理将四个工具回归测试放回 `dc0c3af` 的旧脚本，出现 3 项预期失败，新实现全部通过。没有覆盖工作树来做旧版验证。
- 暂存范围限定 13 个相关代码、回归与文档文件；暂存 diff 检查和敏感内容扫描通过。
- 本轮继续仅运行 TestPilot 合成 fixture，未运行原项目测试、生产操作或 push。

运行时的 UTF-8 重启只作用于探针/检查器自身及其子进程，不修改调用者 shell、系统 locale 或源项目环境。Markdown 检查器仍只支持简单 inline 链接，不覆盖 reference-style、复杂嵌套/特殊分隔符或 fragment 锚点验证；不能把文件存在性检查当成完整 Markdown 验收。

P0 已知审查缺陷关闭，可以按既定 P1 工作包继续；这不等于真实 Runner、注册身份、符号链接隔离或原项目业务测试已通过。
