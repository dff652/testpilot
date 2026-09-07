# P0 运行时最小实验结论

日期：2026-09-07。状态：已在当前 Linux 主机完成合成 fixture 实验；其他平台仍未验证。

## 结论

首版 CLI/Runner 确定使用 **Python 3.12 + Linux**。选择依据是维护成本：Agent Mail 已有只依赖 Python 标准库的 `scripts/dev_sop.py`，其动作清单、结果写入、进程组取消和运行记录可以作为现有实现参考。Node.js 20 在同一台机器上通过了候选实验，但没有做速度 benchmark，因此不能据此宣称 Node 更快或更慢。

这项选择不表示 TestPilot 已经实现生产 Runner，也不表示其他操作系统已获得支持。后续若要支持其他平台，应重新验证进程组取消、超时兜底和残留进程检查，并为平台差异补充适配器。

当前通过结果来自 UTF-8 环境。复审发现非 UTF-8 locale 下探针失败（[R4](review-unpushed-2026-09-07.md)），尚未修复；因此此处不是任意 Linux locale 的通过声明。

## 可复现实验

在仓库根目录执行：

```bash
make probe
```

脚本只使用 Python 标准库和临时目录，Node.js 只作为可选候选运行时；不会安装依赖、调用任何源项目命令或写入项目运行目录。它向 stdout 输出一个 JSON 摘要，`overall_status=passed` 时返回 0；必需检查失败或已发现的 Node 候选检查失败时返回非零。Node 不存在时记录 `not_available`，不阻断 Python 主检查。

本次实测环境和结果：

| 项目 | 结果 |
| --- | --- |
| 主驱动 | Python 3.12.3，`/usr/bin/python3.12` |
| 候选运行时 | Node.js v20.19.2 |
| 平台 | Linux x86_64，`os.name=posix` |
| literal argv | Python、Node 均通过；带空格、中文、`$(touch ...)`、`; &` 的参数原样到达子进程，marker 未创建 |
| 进程组取消 | Python、Node 均通过；显式 ready 握手、独立进程组、SIGTERM 超时后 SIGKILL 兜底，父进程和子进程均退出且被回收（包括 zombie 检查） |
| Markdown round-trip | 通过；中文路径 `知识库/示例 文档.md`、当前 UTF-8 locale 下读取、路径范围、SHA-256 和 JSON round-trip 均一致 |
| 总体 | `passed`；推荐 `python3.12-linux` |

Markdown fixture 的本次 SHA-256 为 `d79d82d5ea27db64dde78f98b56d7e234c01cd6b275fe21441a4020df3a1cfb4`。fixture 在临时目录中创建并在进程退出后删除，不属于项目知识或运行证据。

## 实验覆盖与边界

literal argv 实验使用 `subprocess` 的参数列表和 `shell=False`，通过子进程 JSON 回显确认参数没有被 shell 解释；`$(touch ...)` 仅是合成输入。进程组实验先等待父进程和子进程写出 ready 文件，再发送 SIGTERM。两个 fixture 都故意忽略 SIGTERM，从而验证超时后 SIGKILL 兜底和无遗留进程，而不是只验证一个顺利退出的 happy path。

Markdown 实验在含中文目录和文件名的临时目录中写入 UTF-8 内容，读取原始字节计算 SHA-256，再将路径、内容和摘要 JSON 编码/解码，检查值和路径范围保持不变。

这次实验没有测量吞吐、启动速度、并发规模、真实项目命令、共享服务、网络、模型调用或生产日志。通过结果只证明这些最小机制在当前 Linux 主机上可复现；不等于项目适配器或业务验收已通过。

主代理复核后收敛探针，并使用 Linux subreaper 回收被强制终止父进程的后代；不把 zombie 当成无残留。探针是独立进程，此设置不会修改调用它的 shell。Node 候选实验验证了 Node 子进程和它的后代，不是另写一套 Node 调度器的端到端对比。

JSON Schema 0.1.0 与 `jsonschema==4.26.0` 校验依赖已在独立契约任务完成；探针本身仍只使用标准库。

## 参考实现

- Agent Mail 现有标准库 Runner：`/home/dff652/my_project/agent-mail/scripts/dev_sop.py`
- Python 3.12 `subprocess` 文档：<https://docs.python.org/3.12/library/subprocess.html>
- Python `jsonschema` 校验文档（契约任务参考）：<https://python-jsonschema.readthedocs.io/en/stable/validate/>

- Linux subreaper 语义：<https://man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html>
