# Contract fixtures

`valid/` 是合成协议样例，零值 hash/commit 为占位；其中 result 的 `passed` 只是用于校验成功状态格式，不代表实际项目测试通过。`tests/contract-cases.json` 对样例作明确变更，定义合法状态和必须拒绝的输入，可离线重复验证。

P0 无执行入口：action 文件不得直接执行，Schema 校验不证明命令安全、报告存在、来源可信或验收已完成。P1 必须把注册表、执行版本、产物 hash 和运行结果交叉校验。

`pilots/` 是经源文件路径、提交和内容哈希标识的三份声明；parser 是待实现适配器 ID。这些声明通过结构校验，但没有执行器，不应直接运行。Go 动作的隔离环境由适配器准备，未满足前置条件必须 blocked。
