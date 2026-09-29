# TrainingBridge 返修 C5 独立审查 — 2575deb2

## 0. 结论

**NOT_CLOSED_ENGINEERING。**当前仍有两个已复现的内容校验缺口，以及一个最终交付缺件问题。不是研究统计 FAIL；不重开 R25；不否认已经发生的真实 256 步工程 PPO 更新。

接受本轮已经修好的具体行为：result/source 与 exposure/iteration 关联、缓存 pack 污染拒绝、六类共享消费准备及 bank/reference 边界接入、原有 wrong source/bank/seed/auth 冷读负例，以及异常/未终结 optimizer 预约的保守配额。不能因尚未整体关闭，把上述成果推倒重做。

本次没有修改 GitHub、Notion、用户配置、上传原件或历史账本。Notion 不创建、不更新。

## 1. 实际对象

- 上传包：`RouteC_QualifiedInput_TrainingBridge_v1_RETURN_TO_CHATGPT(1).zip`。
- SHA-256：`0e82e8add2916b9b43dbac6271c9295f6e8bf83a71ae6822e88df9df80705794`。
- 实测：5,956,953 B；506 普通文件；505 条内部摘要精确覆盖；22,683,433 B 解压总量。
- 代码候选 C5：`7c5fcc4f2bcb19b6c659e3f88b43ecffe371f7e5`。
- 本次 GitHub 读取的分支 HEAD：`2575deb2595fd366e6830774214706ea743d1493`；C5→HEAD 为证据提交，没有新业务源码变化。
- 基线：`5ac420a1e6eb50ddd55f0a2969f4cf4ff2b3560a`。

CRC、路径/类型、大小写重复、清单精确覆盖均通过。三个包外文件的摘要与实际上传包一致。13 个 candidate_source 文件的实际 SHA/字节与包内 source manifest 一致；其中下面三个关键模块另取 GitHub 整文件 blob 身份对拍一致（不扩称全部源码远端对拍）：

| 文件 | C5 Git blob |
|---|---|
| ppo262_qualified_input.py | 14cf48a1152037466d9a141befddfe6f452d73f1 |
| ppo262_eng_profile.py | 2a63efde01ffaaf48ed2ef865190da145f2d0375 |
| ppo262_entry_specs.py | 3459b462fdf778ef7cb767204dedb6d0c4b21186 |

主模型 `11bc9a9991bc197bd6570607f8efb184436d2e05da4d21a1f0a39a0f382fbe57` 与上次上传主模型逐字节一致，本次不重复训练、反序列化或前向。此前独立检查实际权重与优化器状态的结论继续按原身份保留，不冒充 C5 新训模型。

## 2. 方法与范围

`probes/run_components.py` 执行包内完整 C5 QI/bank/profile/CLI/EntrySpec 模块，未改目标装载器、迁移判定、冷读控制流或配额实现。本地没有用户 WSL 的 gymnasium/SB3/datasieve；外部环境身份与 V2 装载用“原有效记录＋原 envelope 字节白名单”的依赖胶囊隔离。胶囊只接受与上传有效 envelope 完全相同的字节，不把任意输入判为有效。规划数量采用小的测试值；这些不是项目正式配置数值，不能用来证明实际教学预算。

- generator 在参数观察钩子/消费边界停止；原生生成 0。
- 冷读在 `PPO.load` 边界停止；模型反序列化/预测 0。
- 配额测试使用 learn 异常桩；真实 optimizer 更新 0。
- 实际 `_verify_identity_at_commit` 在隔离新建的本地 Git 仓库运行；用户仓库只读，未修改候选代码。
- 未在助手环境跑全套项目测试，没有把受控组件检查冒充用户 WSL 原生端到端复验。

共 **26 个检查用例，20 个达到预期，6 个暴露漏检**。6 个漏检围绕下面两个问题，不能说成六个彼此独立的新缺陷。`probes/RESULT.json` 与 `execution.log` 为真实输出。

附 `probes/reproduce_remaining_native.py`，可在已有 WSL 部署依赖下运行相同两个问题的正反例。该脚本本次只做了语法编译，未在用户 WSL 执行；它不 fit、不生成 episode、不加载模型、不调用 learn。主 Agent/reviewer 应保存其原生结果，不把本地胶囊结果升级为原生证据。

## 3. R1 — 迁移代码身份空集会自动通过（M01/E03，关联 I02）

### 事实与反例

`ppo262_eng_profile._verify_identity_at_commit(recorded, candidate_commit)` 按调用者提供的 `recorded` 字典逐条校验；字典为空时循环不执行，直接 `return True`。commit 也只在循环里由 git 验证。

独立实际结果：

| 用例 | 预期 | 实际 |
|---|---|---|
| 隔离仓库中真实单条模块哈希 | 匹配 | True，正常 helper 对照（不是完整 manifest 合同正例） |
| 同模块错误哈希 | 拒绝 | False，正常负对照 |
| 空 recorded + 有效 commit | 拒绝 | **True** |
| 空 recorded + `not-a-commit` | 拒绝 | **True** |
| 完整 cold-read，原有效 checkpoint 只清空 `code_identity_consumer` 并置迁移 commit | 模型加载前拒绝 | **到达 PPO.load 边界** |
| 同上，commit 为 `not-a-commit` | 模型加载前拒绝 | **仍到达 PPO.load 边界** |

完整冷读正例、错误 pack/source/bank+seed/auth 的现有控制均符合预期，排除了“整个校验器恒真/恒假”的解释。

这是已登记 Cq/Ct 不同版本的迁移兼容路径漏检，不应通过禁用全部迁移来修。合法旧 C2 模型必须仍可按其真实版本合同复验。

### 修复完成条件

1. 迁移前校验合法完整 commit 身份以及该历史 manifest 版本必需的模块集合；空集合、缺必需模块、任意子集不能自证完整。
2. 必需集合由可信的版本/候选合同确定，不以待验 manifest 自己列了多少项为准。不要仅加一条 `if not recorded` 就遗漏非空但不完整集合。
3. 每个必需模块仍逐字节对拍归档，并保留与当前消费合同兼容性的验证；不要把“能在某个历史 commit 找到”当成所有当前行为漂移的通行证。
4. 正例：原提交模型+合法显式迁移 sidecar 仍通过；反例：空映射、删任一必需键、非法 commit、错模块字节，均在 PPO.load/预测/更新之前拒绝。

## 4. R2 — fit 来源声明没有与 bundle 内真实来源对上（V01/I01/I02，关联 N01）

### 事实与反例

当前装载器检查 plan 的 `preprocessing.fit_namespace` 非空且不在训练/评估 namespace 集合；它没有把这一声明及 `fit_fixture_records` 同实际 envelope 的 namespace/fit manifest 逐项关联。V2 envelope 自身校验不能代替“两份独立文件之间是否一致”的校验。

在原有效 envelope、pack 完全不变的隔离副本上：

- 仅把 plan 声明的 fit_namespace 改成另一个不在禁止集合中的名字，一致重算 plan/result/exposure/工程授权的外层摘要，**装载仍通过**。
- 仅把 plan 的第一个 fit_fixture_record.episode_hash 改成一个虚构值，同样保持外层摘要自洽，**装载仍通过**。

改变 envelope 本身的负对照会被拒绝；fit namespace 直接改为训练 namespace 的旧反例也已拒绝。因此问题不是旧反例没修，而是“不同名但错来源”的剩余关联缺口。

这两个反例均为工程夹具副本；没有伪造正式许可，也没有发现真实 fit 数据已污染。它们直接检验原 NEXT_GOAL §3.2 要求的“生产 fit 来源依资格输入声明逐一验证”。

### 修复完成条件

1. 用当前已有的 V2 provenance/manifest 实现，验证声明的 namespace、源 episode/feature 身份、角色与包中实际 fit manifest 对应；需要派生映射时说明真实映射，不凭路径或显示名判断。
2. 命名空间没有交集不等于来源正确。保持正确来源的同字节移位/合法表示转换可用；实际来源不一致必须拒绝。
3. 原数值不同来源、来源条目缺失/替换、声明与 envelope 不一致的负例，必须在生成/更新前拒绝。不得为了回避验证而静默删除来源声明。
4. 本轮只完善消费校验，不扩展正式资格生产或重新生成训练数据。

## 5. R3 — 当前 RETURN 缺 C5 适用的 v5 回归原件（R01/A02，交付项）

包内实际只有 `regression/full_regression_v1` 至 `v4`、`regression_262_v1` 至 `v4`，以及 `ALL_RC_V5.txt`。没有 `full_regression_v5/` 和 `regression_262_v5/`。

已逐 testcase 解析包内八份 JUnit；四轮 261 都为 2541=2534+7skip、0F/0E，collection/JUnit 多重集相同；262 v1/v2=204、v3=224、v4=225，均无失败。v4 绑定 C4=`dec94b85`，不能当 C5=`7c5fcc4f` 适用回归。

GitHub@2575deb2 已列出 v5 真实原件；本次另读 `full_regression_v5/summary.json`，其 ok=true、2541/0F/0E/7skip、record_sha=`8d58d0798520e20a94d38064157b88e47d5d0531e406af5dcfc3c2241dad4301`。这说明材料有具体归档位置，**不是宣称 Agent 没有运行 v5**。本次没有取得并复算远端全部 v5 原始文件，不能把 summary 当作已做原件终验。

原 RETURN_REQUIREMENTS §2 明确要求 ZIP 包含 261/262 适用原始输出/JUnit/审计及源映射。请从已归档对象按原字节补入 v5 两套完整记录及 launcher rc；文件级读回并核对候选/record/collection/JUnit。此项本身只需补件，不为补件重跑回归。

包内 ALL_RC_V5 与仓库旧汇总件的已披露更正、历史 rc=3、跨进程 float32 概率残差、本轮 reviewer 后端模型元数据不可见等，不另外开阻塞。最新代码修复后若出现 C6，仍须提供 C6 自己的适用验证，不把 v5 改签为 C6。

## 6. 已完成的 reviewer 补件与本次保留项

本轮 `reviewer_originals` 与 `reviewer_originals_v2` 已有旧/新独立脚本、结果与 C4 FAIL→C5 PASS 的增量报告，之前“只交 reviewer 结论而无原始检查”的主要缺口已改善。不能因为本次仍发现漏检，就说 reviewer 未工作或未发现任何问题。

继续保留：完整包级 CRC/SHA 检查、来源 iteration 两项交叉校验、缓存 pack 拒绝、六类共享 EntrySpec 管线实调用点、旧冷读 source/bank/seed/auth 负例、配额预约/异常保守计数、旧 R2 缺省路径和工程/正式分离。没有 Notion 工作。

## 7. 返修流程、配额与交付

沿原 TrainingBridge 任务返修；不恢复默认 8 小时时限。主 Agent 实现与基础自测后，必须真实调用已配置的 `reviewer`（预期 `zhipu-coding-plan/glm-5.3-flash`）独立验收。Reviewer 收到本报告、原要求、原矩阵、候选和原件，不只读取 SUMMARY。FAIL→主修→独立复验；最后对实际最终 RETURN 冷读，签包外回执。不能代签、伪造模型元数据或选择性保留 PASS。

原生重放已 2/2，成功 episode 12/12；optimizer 2/8 次、512/2048 步。主模型字节仍与旧模型相同。补件、来源匹配及身份拒绝正反例均可先零新增原生生成、零 fit、零 optimizer 完成；不为这三个问题重跑旧研究、R25、G5c。源代码改变时产生新候选并做直接适用回归；需要超过原生配额的端到端运行须明确申请，不重置计数。

闭合条件：R1/R2 真实依赖正反例与合法旧迁移正例通过；完整原矩阵对最终身份对账（未影响项可合理复用）；当前最终候选适用原件随包；独立 reviewer 内容+封包两阶段通过。尚未满足时报告未完成，不签 CLOSED PASS。
