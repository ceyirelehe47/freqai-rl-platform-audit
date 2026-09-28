# RouteC_R25_ProposalEvidence_SelfAcceptance_v1 交付总结

交付状态建议：**READY_FOR_INDEPENDENT_REVIEW**（Agent 内容面自验收 `SELF_ACCEPTANCE_PASS`；最终 ZIP 封口回执见外部 `DELIVERY_RECEIPT.md`；**ChatGPT 独立终验未做**，本包不构成 CLOSED PASS）。

- repo：`ceyirelehe47/freqai-rl-platform-audit`；branch `route-c-stage2-6-1-repair17`。
- 观察基线 HEAD（发包时）：`e0cdd5ea3ac6a1d7500e61e0759f72509fd46850`。
- 原代码候选 C：`7e9e5470889884bad296a2dbb4b3e55ca38bc151`（本轮**零代码变更**，执行面与 C 完全一致，其 WSL 全量回归/真实集成经只读双通道核验后**复用**，非本轮新跑）。
- 本轮提交：纯文档/证据（提案 v2、只读核验器与结果、README 索引追加）；最终 HEAD 见 git_receipts/。

## 1. T：训练提案 v2（本轮主交付）

`report/route_c_stage2_6_1_qualification_to_training_proposal_v2.md`（包内副本 proposal/）。开篇撤回 v1 三项错误主张：

1. 撤回「r_true≈0.98（及一切同义表述）」——估计 SE 比值（≈0.98，同量级描述）不是 r_true 的估计；r_analysis=1.5 是抽样前固定分析约定，不是已证真实上界；±0.003 是开发分析分界，不是生产容忍度。
2. 撤回「input-lock 13 项已可绑定新资格/数据前门槛全部已有入口」——现有锁硬绑历史 R2（固定 digest 常量 qp-8f64a1b5…、R2 artifact 目录、causal-unscaled 边界、14 项 checks）；§4 给出 A1–A8 最小接入清单（已有/待实现/待决定逐项）+6 正反例 + 主分区角色映射。
3. 撤回「批准后现有入口可直接推进（无缺口）」——v4 聚合在正式链**无消费者**（唯一消费者=开发研究入口），且现有 `cmd_cue_audit` 单次运行=单 namespace 对，**无 K 自动生产路径**；§5 落实判据关系（附加确认层，不替代/不豁免任何既有 gate；分区 gate FAIL 不可被聚合 CI 救回）、K 输入的生产与消费入口均显式待实现（r20_formal_coordinate_runner / r20-formal-aggregate）、不足 K 代码事实强制不决、停止规则 Level A/B 分层（D-2 事前二选一）、链外 provenance-lock 时序、新迭代/状态根隔离适配。

推荐路径（§6）：P0 签收→P1 科学决定（D-1/D-2/D-3/D-4）→P2 provenance-lock（Commit A 前）→Commit A→同步→P3 admission（含坐标清单 manifest）→P4 Level A 资格链（17 步）→P5 Level B 确认性研究（坐标 runner+聚合，待实现）→P6 接入工程轮（待实现）→P7 训练阶梯（ppo-smoke=首次参数更新→config-dev→probe→core→final）。预算只用实测锚（回归 2619.25s、开发批次≈50min），正式链全链/MC/global-K/core/final 如实标未知并给监护上限。

SELF_REVIEW_CASES 14 条实际回答见提案附表 B（逐条指向章节/源码定位）。

## 2. E：已有原件核验（只读，双通道）

- **E01**：FinalClosure RETURN 原件（outgoing/，未动一字节）SHA=87d7c88b…（811531B/123成员/3222154解压字节/CRC全过/无危险成员）；内层 Binding ZIP=8aab7aa7…（530428B/124成员）与 outgoing 独立原件同 SHA；包内 SHA256SUMS 122/122 精确覆盖。逐成员清单 E01_MEMBER_MANIFEST.json。
- **E02**：7e9e547 全量回归——独立复算（record 611b234d 重算一致、JUnit 逐 testcase 2541=2534p+7s、collection multiset==JUnit、7 skip 具体 ID record==JUnit、stdout 汇总行 2619.25s、r24 审计 verdict=pass/零违规、源面 315+148 CR 规范化全等）+ 仓库权威核验器（WSL 同解释器、含部署面）VERIFY_OK。旧 990dbcf 回归 repo 侧 VERIFY_OK（2522=2515p+7s；deploy 对拍差异=部署树已随 7e9e547 前进，同轮 deploy 全过为证）；旧 721b314 失败回归 VERIFY_FAIL `regression_not_green`（1×C07 真实保留，不修绿）。
- **E03**：5 个监护 run（2 新+3 旧）required 逐成员大小/SHA 全对账；真实集成 w1/w2 rc=0、w3 原始 124、三 checker clean、registry v2 身份完整（多重集/pid/ticks/root）；包内 26 监护成员与 repo 逐字节相同；rc=4 run 的 worker_exit incident 真实保留。

## 3. P01 历史保护

冻结树 plan df7d04de / smoke 3ef2fc55 / study 96df8ff9 三方一致（HEAD 复算=上轮前后测=Binding 轮 freeze）；vendor 52bc96f4 clean（WSL 实测）；零新研究/训练/许可消费；11 坐标未重跑；MISSING 历史保留。

## 4. 本轮已执行 / 未执行

已执行：只读核验（含 WSL 权威核验器×4 与 vendor 只读检查）、提案 v2 撰写、README 索引追加（只增不改）、用户授权的工作区清理（goal_incoming 旧轮归档+分支清理，账目 archive/REORG_MANIFEST_F_20260929.tsv，不影响任何本轮证据）。
未执行：正式 R20 注册/抽样、正式 cue-audit/audit、资格/exposure 消费、BC/PPO 训练、11 坐标重跑、G5c 重训、任何 pytest 全量（复用 7e9e547 原件）、A2–A7 接入实现（提案方案，非实现）。


## 5. 独立审查后的第二轮修订（2026-09-29，REVIEW.md）

独立审查结论 NOT_ACCEPTED_AS_SELF_ACCEPTANCE_PASS，两项实质缺陷已在本轮内修复并重验：

1. **E03 正文复核（REVIEW §2）**：首版核验器的序列/覆盖检查取自 summary 计数、未重算遥测正文，审查方以 SYNTHETIC 反例证明漏检。新增 `e03b_verify_supervision_content.py`：guest/win seq 重复/回放、五项峰值、per-pid 身份稳定（inst_start_ticks/reused_pid）、相邻样本正 CPU 增量、registry 实例 pid⊆遥测观测集，全部从原文重算——真实 5 run **ALL PASS（重算==declared，rc=0）**。`synth_e03b_counterexamples.py` 以 SYNTHETIC_ONLY 夹具复现审查反例：seq=1,1,0、空覆盖、伪峰值均被 rc=2 拒绝；sha_tamper 负对照正确触发 required 防线；健康对照 rc=0。旧 summary/遥测零改动；本轮核验命令 argv/rc/stdout 全部落盘（E03B_REAL_RUNS_EXECUTION.log / E03B_SYNTH_EXECUTION.log / synthetic_cases/*/run_log.txt）。
2. **T03/T04 依赖闭合（REVIEW §3）**：提案 v2 第二版（文件头修订记录显式标注，非默默替换）——§5.3 补 K 坐标**生产**入口 `r20_formal_coordinate_runner`（admission 预注册冻结坐标清单 → 逐坐标调用现有 `cmd_cue_audit` → manifest digest 绑定）与消费入口 `r20-formal-aggregate`；§5.4 停止规则按 Level A（资格链，现有规则不变）/ Level B（K 坐标确认性研究，D-2 事前二选一）分层；§5.5 新迭代/状态根隔离适配（独立确认性研究根、不经环境变量、白名单扩展、验证方法=错根拒绝+旧根零写入断言）；§6.1 P2 顺序统一为 provenance-lock（Commit A 前）→Commit A→r21_sync；§6.3 分层失败出口。附表 A 增补"单 namespace 对运行/无 K 自动生产路径"与"白名单机制"两行。
3. **S01/D01**：自验收报告 §2.1 如实记录第二轮失败→修复→重验；第一轮（976e1e96 前）原始命令输出未逐字落盘属事实，不追溯补写；本轮重新提交并重新封包，外部回执锚定**新 HEAD 与新 ZIP 最终字节**（旧 ZIP/旧回执作废，见 DELIVERY_RECEIPT）。

## 6. 本 ZIP 身份（第二版封包）
主文件：`RouteC_R25_ProposalEvidence_SelfAcceptance_v1_RETURN_TO_CHATGPT.zip`；SHA256/字节数见并列 `.sha256.txt` 与外部 `DELIVERY_RECEIPT.md`。上轮 FinalClosure 原 ZIP 原字节嵌套于 `previous_round/`（其内 Binding ZIP 原样保留）。任务包 `RouteC_R25_ProposalEvidence_SelfAcceptance_v1.zip`（输入）不重复携带，其 SHA 记录于 DELIVERY_RECEIPT。
