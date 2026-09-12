# 实现与验证范围

## 已实现

仅修测试成功前提，不改 guard：pipeline `_claim_fixture` 延迟导入并复用 claim_protocol 已有健康构造函数。后者提供 synthetic 合同、非空 fixture source identity、create-only evidence/plan/receipt 和真实临时包摘要。未传 runtime 不再调用 sources 为空的 `fixture_runtime()`。

延迟导入的目的只是避免两个测试模块在收集时的循环初始化；没有 monkeypatch 校验函数或伪造返回 PASS。原 V10 测试断言保持逐字不变，新的坏夹具测试在 temp 中恢复旧错误形态并要求继续拒绝。

应用器以整文件 Git blob 固定 preimage，在内存完成变换、确认其他已有函数/类不变和编译后才允许单文件写入。recovery 保存原工作树字节、Git字节及新输出，无自动 rollback/reset。

## 本地已实际执行

Linux / Python 3.13.5：33 个包级测试通过，0 fail/error/skip。原始证据见 `local_validation/`。

范围包括：

- pinned applier 的只读check、单文件apply、原测试体保持、错误HEAD/blob/锁/payload、dirty目标和recovery拒绝；应用集成使用临时 Git 测试仓库，不是用户实际仓库。
- 新 `_claim_fixture` 的委托/默认runtime/deepcopy/异常传播。**这部分使用测试替身观察 helper 调用，不是实际 claim 端到端执行。**
- 原 v3 不改字节 builder 生成实际临时包，原 v3 guard 对其 semantic 检查和坏文件拒绝。
- 原 v3 guard 在真实临时 Git 仓库接受 C→continuation_v3a/E→E2，拒绝改写旧失败报告和不在既有白名单中的平级根。
- 定向 JUnit 检查器按实体状态和必要 V10 case 判定。

另已对工具/载荷做 Python 编译和两个 shell 脚本 `bash -n`。

## 未在助手环境执行

- 未取得用户整个可运行 checkout；网络下载不可用，不能声称完整 checkout 应用已完成。
- 未在本地运行实际 pipeline 模块的全部42项或修复后的原 V10 与完整 claim 链。
- 未运行 WSL Python3.11.16 的八文件157项、全量回归、真实监护/native或最终交付冷验。

这些是 Agent 本轮的必验项，必须使用已部署真实模块，不用包级测试替代。33个本地PASS不代表R17工程已PASS。
