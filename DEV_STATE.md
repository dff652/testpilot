# Development State

## Goal

创建独立本地仓库，归档 TestPilot 调研与实施方向，明确开发准备、任务分工和验收条件。

## Verified current state

- 2026-09-07：初始化 `/home/dff652/my_project/testpilot` 的本地 main 分支。
- 内容为开发准备文档；产品代码、JSON Schema、Runner、适配器和索引尚未实现。
- 上一轮已读取 NAS 原文章及源码配图；文章对应仓库仍未核实。
- 主代理复核 Agent Mail 的动作清单、结果 schema、SOP 并发边界，以及 AI Asset Hub 检查脚本、TS Platform 并发约束、homelab-doctor Makefile。
- 本机工具读数：Python 3.12.3、Node.js v20.19.2、Git 2.43.0；未安装或升级依赖。

## Decisions

- CLI 优先；首批 Agent Mail、AI Asset Hub、homelab-doctor。
- 项目原生文档为事实来源，索引可重建，运行证据单独管理。
- 主代理负责共享契约与最终验收；luna-worker 执行有明确文件边界的任务。
- 技术栈、正式 schema 和验收样本在 P0 最小实验后确定。

## Validation

2026-09-07 初始文档已由主代理审查，修正文中版本号表述和首版 CLI 范围。检查结果：

- `git diff --cached --check`：通过。
- homelab 的 `tools/repo-doctor/check-markdown-links.py`：11 个本地引用通过。
- homelab 的 `tools/repo-doctor/scan-staged-secrets.sh`：暂存新增内容扫描通过。
- 临时只读校验：61 处源文件路径存在且行号范围有效；不代表这些引用涉及的功能已运行验证。

检查工具在本机相邻 homelab 仓库中，尚未纳入 TestPilot 的可移植开发工具链。未执行产品或原项目测试。

## Next action

完成 [开发前准备](docs/preparation.md) 的 P0：三个动作清单、schema 样例、技术选型实验与隔离验收 fixture，再开始 P1。

## External state

未配置远端、未 push、未部署、未写外部知识服务。许可证和公开名称尚未确定。
