# 单文件修复与验收续接任务书

任务 ID：`R17V2C13V10FixtureRepairAndVerificationResume-v3a`

## 1. 已发生的事实与本轮完成定义

`1ea193c0f1eb710e37aa23aa89f261617eb93c43` 是旧 v3 给定实现及失败证据提交，不是合格候选。S2 监护定向共 152 个 case，151 通过、1 失败、0 error、0 skip；唯一失败为 pipeline 的 `test_v10_one_shot_claim`。旧 v3 全量回归、包副本负例、E 后冷验都尚未执行。

本包只修助手遗漏的成功夹具，继续完成尚未完成的 v3 验收。旧失败提交与旧失败报告永久保留；本轮成功不追认旧失败轮。

完成条件：单文件补丁已准确应用；原 V10 成功/永久消费断言通过；新四个不健康形态继续被拒绝；八文件定向零失败/错误/跳过；同一新候选完成一次完整 R17-first 回归、真实包副本负例及 E 后 full 冷验；保护对象不变；普通提交推送。

## 2. 固定接手与修改面

仓库 `ceyirelehe47/freqai-rl-platform-audit`，分支 `route-c-stage2-6-1-repair17`，HEAD 必须为 `1ea193c0f1eb710e37aa23aa89f261617eb93c43`。

应用器只修改：

`stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_pipeline.py`

只替换 `_claim_fixture`，追加两个测试函数（一个单 case，另一个四 case）。原有测试函数不变。修改后的成功夹具依赖已安装、已实机测试过的 claim_protocol 私有辅助函数；导入发生在调用时，不在模块初始化时。

**禁止重签 source lock。** 本包没有修改被治理 lock 覆盖的十个生产成员；source_guard 应仍与失败提交一致。测试文件的新身份通过新候选 Git tree、collection、test_files.sha256 与完整回归绑定，而不是改变生产源码锁。

## 3. S0：接手及历史保护

fetch 后核对本地、远端及分支。远端不同或源码/测试/配置有未知更改即停止，不自动 pull/reset/rebase/stash。

固定 WSL：CryptoRL-Ubuntu-24.04，cryptorl，freqtrade-rl，Python 3.11.16。发布库 `/mnt/f/trading/freqai-rl-audit`；部署 `/home/cryptorl/projects/crypto_rl`；runner 为部署下 `stage2_6_1_runner`；vendor pin 保持 `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。

沿用上一轮已经成功的只读区字节快照方法，额外保护旧 v3 失败根在本次接手时已存在的全部文件。以下对象不得改变：旧 v1/v2 claim、旧实验树、旧 postrun/governance 归档、旧 v3 REPORT 与原始失败日志、历史 lock 和当前治理 lock。

历史 lock SHA 必须仍为 `c9152b62192a93571c16ba62e0ef2e70522f108726f3eb83fd25d48007a77c55`。记录活动 run_supervision 的 M/??，不删除、不混入提交。新 continuation_v3a 是唯一允许新增的证据子树；保护检查按接手时的既有文件逐一对拍，不能把合法新子目录误判成旧原件变化。

## 4. S1：应用与同步

验证本包 SHA256SUMS，默认 check，再 `--apply` 指定全新仓库外 recovery。应用器验证 HEAD、target blob、支持夹具 blob、源码/测试/配置 clean、历史 lock 字节及 payload；只写上述一个文件。

输出 diff 必须恰为该测试文件，原 `test_v10_one_shot_claim` 和 `test_v10_corrupted_claim_is_consumed_not_retried` 测试体逐字不变。用既有 r17_sync 同步，核对发布/部署测试字节（沿原 LF 同步规则）及 source_guard 十成员。不要运行旧 v3 应用器，不运行任何 relock 工具。

## 5. S2：八文件定向重验

运行给定 `tools/run_targeted.sh`，经原监护入口一次跑八个关键文件。保留完整 entry/business stdout、stderr、rc、JUnit、run_record、required/native、源 before/after、测试文件 hash。

本轮新增要求：健康 fixture 实际回归包存在，receipt digest 真实，contract.synthetic_profile=true，source identity 非空；只读 validate_claim_admission 不写 claim；structural fixture 不能变成生产 admission_eligible。

四个独立临时变异必须各自到达预期拒绝层，且 claim 未创建、输入未被 verifier 改写：生产合同替代 synthetic 合同；回归包缺失；fake aa 摘要；admission evidence 缺失。仅变异 pytest 临时副本，不改生产文件。

定向出现任何失败/错误/跳过即停止交付失败；不为绿色放行旧夹具，不改成功预期为“抛异常”，不使用 -k/-m 排除 v10。预计 157 case，仅作计数检查提示，不是可凑数的指标。

## 6. S3：新候选 C

定向通过后普通提交这一个测试文件并 push。失败基线的 v3 九文件补丁已经在父链中，不重复 staging 或还原。现有 v3/** 的 -text 规则已覆盖 continuation_v3a，本轮不需要更改 .gitattributes。

C 后重新同步/核对源和测试，源码/测试/配置 clean。C 必须包含本次夹具修复；不能用 `1ea193c…` 的失败测试结果背书 C，也不能把旧 source closure 相同理解为测试候选相同。

## 7. S4：原 v3 尚未执行的一次完整回归

使用随包 `tools/run_bound_regression.sh C_SHA FRESH_EXTERNAL_WORK_DIR`。该脚本从原 v3 包逐字沿用：R17-first、完整测试集合、原监护入口、原 collector、源代码固定 critical/skip 策略与 full verifier。

仅同候选完整回归成功才进入下一阶段。历史七个 skip 按 source-owned allowlist；不得新增 skip。本轮关键测试不得 skip/xfail。真实总数从 collection/JUnit 取得。采集器失败和测试失败分阶段记录，不写成统计 FAIL。

源/测试/配置改变必须停止，不能沿用已有回归；证据提交本身不触发重复全量测试。

## 8. S5：健康包与副本负例

使用随包原 v3 `tools/probe_evidence.py`。只读 full 健康控制及八种副本负例全部保留 verdict、mutation、原始命令/stdout/stderr/rc。原健康包不修改；不以 structural 替代 full。

脚本测试 required 空/重复、critical 空、隐藏 testcase failure、collection 等数量换人、import 缺来源、supervisor rc 缺失、目录 symlink。负例必须按预期错误键拒绝，不只统计报错次数。

## 9. S6：续接证据 E 与提交后冷验

全部新证据只归档到：

`stage2_6_1/artifacts/repair17/development/v2_c13_admission_boundary_closure_v3/continuation_v3a/`

该子树在 C 中必须不存在。C 前的测试/应用证据保存在仓库外，直到 E 统一归档。E 仅新增此子树，禁止重写 C 中任何既有 artifact 或失败报告。子树内独立 SHA256SUMS，不更新旧 v3 根的 SHA256SUMS。

E 普通提交/push 后，在最新 HEAD 对归档健康包 full verify；保留采集时的 C，不回填 git_head_at_collect。`ok=true`、rc=0、validation_scope=full 为要求；未提供生产 authority 时 admission_eligible=false 正确，不得为把它翻真而复制包到生产 claim 根。

可将 after-E 冷验输出放入该新子树做 E2，然后最终再做仓库外只读冷验并报告。不要为自指最新 HEAD 无限增补提交。C→E/E2 之间源码/测试树必须不变。

## 10. 权限与计数口径

新主实验生成、生产 claim/plan/receipt/admission 写入、新 C2 namespace/实验、qualification、exposure、正式 BC/PPO 训练均未授权。旧 v1/v2 claim 永不复用。

既有完整 pytest 内的隔离 fixture、历史组件单元测试和原 smoke 行为沿原 v3 范围运行，不扩展为新主实验。它们可能调用生产组件函数；应分别记账，不能把“零新主实验/零生产 authority 写入”误报成“所有 Python 函数调用数为零”。

## 11. 报告及失败处理

报告首页分开：本次 fixture 修复/续接工程 PASS 或 FAIL；统计 NOT_RUN；正式资格 NOT_ISSUED。列 baseline、C/E/E2、远端、实际定向/全量计数、冷验范围与 rc、旧失败永久保留、保护字节对拍、未运行项。

任一阶段失败保留原始字节并普通提交可审查的失败状态，不创建合格候选语义，不自行改源码或扩大修改面。后续修复由助手下发。即使续接工程通过，旧 v2 工程仍为 FAIL，stored-table strict PASS 仍只作诊断，C2/完整 Stage2.6.1 正式资格不升级。
