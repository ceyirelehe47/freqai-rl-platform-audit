# Route C 本轮独立审查：9be9f1f

日期：2026-09-25。任务：`RouteC_FullCollection_ResearchDesign_NextGoal_v1`。

## 一、结论

这轮有实质交付：完整 pytest 收集/执行采集器、v3 核验、归档的绿色全量 stdout、研究提案与可计算附件、G5c 时间证据勘误。不能描述为“没有干活”或仍停在 ef55c96。

**尚不能整轮签收：A 的有效收集环境仍有一个具体反例；C 的最低复制次数公式有可复算错误，行动规则存在重叠，标准误不确定性处理不足。G5c 的限定措辞勘误可以接受并收尾。**

本次为 GitHub 源码/部分运行原件审查、真实本地 pytest 组件探针和设计数学复算。没有执行用户 WSL 全项目测试，未取得完整 Agent RETURN ZIP，不声称对每个上传原件逐字节全部核验。

## 二、远端与实际运行证据

仓库：`ceyirelehe47/freqai-rl-platform-audit`。
分支：`route-c-stage2-6-1-repair17`。
远端：`9be9f1f61075936a20d27254e4cff6462959e3f6`，提交时间 `2026-09-25T04:21:24Z`。
上一锚 `6392d75d6290281f2ec948f98083d8c9576b3a1c` 之后新增六个提交。
最终报告绑定候选：`e42e07a56044daec76357ca36c4247bed005601d`。

固定路径：
`stage2_6_1/artifacts/repair17/development/admission_regression_evidence_v3_closure/full_regression_20260925/`

直接读取的 stdout 末行：`2338 passed, 7 skipped, 10 warnings in 2575.68s (0:42:55)`。
`summary.json`：2345 tests、0 failures、0 errors、7 skipped；两段 rc 均为 0；collection_tests=2345、static_tests=1882、test_files=144、ok=true。
record SHA 声明为 `25aa94989d9025e1b9f675dad316793c515cfac480beb1893debfc687d66bcbe`；本次读到声明，未把声明直接等同于完整包摘要复核。

报告另称 Stage 2.6.0 受影响面 182 passed。它不是 Stage 2.6.2 的本轮全量结果，也不是 182 次研究实验。

## 三、A：完成的能力与剩余缺口

### 已落实

原始 `pytest --collect-only -q` 输出被保存并解析，JUnit 与展开 node-ID 多重集合对应，不再只靠 AST 基础函数名。常见显式筛选 argv、PYTEST_ADDOPTS、两个直接定义的收集钩子都有拒绝；多文件去重、父证据递归、元素级 JUnit 检查保留。报告中的正反例与真实签发沙箱体现了改进；最终 full stdout 可读取。

### A05 仍未闭合：实际生效的收集插件未被完整控制

`_reject_config_filters` 只查看 `conftest.py` 顶层直接定义的 `pytest_collection_modifyitems` 和 `pytest_ignore_collect`。它不确认实际生效的钩子集合。导入式 `pytest_pycollect_makeitem` 可在早期收集阶段改变参数实例，且其控制环境变量不在当前记录的两项 PYTEST 环境字段中。

本地真实 pytest 结果（独立合成测试树、相同文件）：

| 模式 | 真实收集 | 真实执行 | 结果 |
|---|---:|---|---|
| 完整对照 | 10 | 2 passed / 1 failed / 7 skipped | rc=1 |
| 导入钩子启用快速模式 | 9 | 2 passed / 7 skipped | rc=0 |

第二行的命令仍指向完整目录、无 `-k`/`--deselect`，stdout/JUnit 均为真实子进程输出，未手动编辑；原始 collection 与 JUnit 一致，静态基础函数集合、测试文件覆盖和七个历史 skip ID 也一致。配置过滤、argv 与摘要等相关函数摘录未拒绝。

这是对任务 A05“环境/config/hook 缩减范围不能获得 full”的现存缺口，不是另行增加防御所有恶意源码的目标。不能用两个同样被筛选的运行彼此一致，证明不存在筛选。反例未在用户 WSL 的完整签发链执行，因此不声称整链绕过；也没有证据表明 Agent 的实际 2345 项运行用了这个钩子。

先前使用 `pytest_collection_modifyitems` 的本地探针被数量交叉校验正确拒绝，原件也保留，不能把该失败探针写成成功绕过。

**收敛要求**：在已有执行入口约束并记录实际加载的插件/钩子与影响展开的条件，建立可信完整收集，再关联执行；不支持的收集扩展必须明确拒绝或预先绑定。不得把正确的动态参数化一律删掉，也不要只追加一个钩子名字就宣称问题类别闭环。先补小沙箱的正反例再收敛，避免再次先跑五轮全量才发现入口问题。

### 运行来源的证明范围

新 runner 的 `_run_pytest` 实际启动 pytest 并采集 stdout/stderr/时间/返回码，优于手写这些字段。但源树 `import_surface` 主要是候选 Git 摘要与事后部署磁盘字节比较；62 个共享部署模块只声明名字，并非其实际导入路径/字节记录。v3 record 不含与该次外层监护运行的独立关联。不能因此把它说成所有运行来源都已独立封口；也不能反向仅凭 runner 未内置监护就断言外层绝无监护。需要复用既有运行锚对应当时真实执行，不另造框架。

## 四、C：研究设计进步，但目前不能照原文执行

### 可保留的进步

旧 K=5、4/5 表决规则已撤回。采用有符号偏差 `delta=p_analytic-recall(validation)`、等效性问题、明确新开发坐标/正式确认分离，比用多数 PASS 推断原因合理。脚本用抽象正态模型而非项目生成器，符合本轮只做设计的权限。

在脚本假定 model 无偏、两语料独立且标准误已知的模型下，delta=0.003 时旧表决 >=4/5 的概率复算为 **0.3859895**，报告的0.386正确。

### C03/C04：最低 K 算法把目标90%换成了80%

对方脚本 `tost_power` 的主要功效公式，与 `part_c_equivalence_design` / `part_e_cluster_sensitivity` 的最低 K 判据不一致。后者采用 `z_0.95+z_0.90 = 1.645+1.282`，并标为零偏差处90%功效。

其自身已知方差正态模型中，对称 TOST 在真实 delta=0 时：

`power = max(0, 2*Phi(Delta*sqrt(K)/SE - z_0.95)-1)`。

所以90%需 `z_0.95+z_0.95 = 1.645+1.645`。对方的连续临界值实际上对应80%；整数向上取整可能提高一些，但不能据此标90%。原 JSON 已显示 K=4 功效0.8519，却仍输出 `min_K_power90_at_zero=4`。

Delta=0.003、SE=0.0019410552950364546 时，独立复算：

| 标准误膨胀 rho | 对方最低 K | 该 K 实际功效 | 正确最低 K |
|---|---:|---:|---:|
| 1.00 | 4 | 85.19% | 5 |
| 1.25 | 6 | 83.36% | 8 |
| 1.50 | 9 | 85.19% | 11 |

这是标准误已按 rho 修正的条件计算，不是真实生成器功效保证。K=8 不因该错误自动无效：rho=1.25 且分析端正确调高标准误时，K8在零偏差处功效约93.60%；rho=1.5时仅79.57%。需把实际分析法、样本量和计算统一。

### C05：等效与“转校准”两条行动可能同时触发

原文规定 CI90 完全位于 (-0.003,0.003) 为等效；又规定同一 CI 下界>0则转校准。两统计陈述可以同时成立，并非数学矛盾；问题在于给它们分配了相冲突、未消歧的后续动作。

例如 K=8、估计delta=0.0015、使用其SE时，CI90约 `[0.0003712,0.0026288]`。它既全部为正，又全部落在容许范围内：这应报告为“可检测到的正向小偏差，且在拟议等效界内”，不能同时被当成重要缺陷和无需处理。

需要按“是否超出已批准的重要偏差界”定义研究决策；若下游要求严格无偏，则必须先修改研究问题，而非一边批准非零等效界、一边把任意非零作为必须修复。

### C01/C03：SE处理不能仅用bootstrap次数说明

脚本把 `1/sqrt(2*20000)` 近似0.5%当作 SE 估计不确定性；这至多是给定数据上有限重抽样的数值噪声近似，不能替代500个原始cluster和跨坐标变化带来的统计不确定性。

各坐标SE不相等时，等权均值在独立且无共享解析不确定性的条件下，标准误应为 `sqrt(sum(SE_k**2))/K`，不是简单 `mean(SE_k)/sqrt(K)`。还有共享解析锚或跨坐标分量时需相应处理，不能只沿用单次R19的SE并声称错误率已经校准。

敏感性要分清“修正分析SE后的功效”与“真实SE被低估但检验不修正的错误率”。K8、真实delta=0.003时，若仍使用原SE而真实SE为其1.25/1.5倍，该正态模型下假等效概率约9.41%/13.64%，并非5%。本附件给出可复算代码。

`Delta=0.003`仍仅是待审建议。噪声大小和检验分辨率不足以单独定义可接受的实际偏差；没有既定下游损失容忍依据时，应明确为开发研究候选界限，不能倒写成旧合同。

## 五、G5c 与交付偏差

G5c 新增的时间勘误准确区分了“文件时间早于完成”与“计划早于训练开始”。这一小项可接受并收尾；数值、历史缺失保持原样，不再重训补证。

工程报告披露第一轮失败目录被下一次启动清理。该次原件只能标为缺失，不能靠提交说明恢复成完整执行证据。另三次失败和最后绿色结果要分别保留；这一缺失不自动否定最后绿色stdout，但也不能说所有失败原件均完整。

被称为 evidence 的 `9be9f1f` 同时修改了可执行的 `runner/r21_sync.sh`。e42→HEAD不是整个执行面零变化；应单列该同步差异及适用验证，不应无条件称为纯证据提交，也不意味着必须无差别重跑全部历史测试。

## 六、下一步与本次边界

仍在原任务内收敛，不需要另起实验：

1. A：补实际有效收集环境的绑定/拒绝与真实签发沙箱反例，复用既有运行来源锚；保留已有正确参数化/分片/父证据防线。
2. C：纠正最低K计算、SE不确定性及行动分类，给出与实际分析法一致的样本量/错误率依据。无需新项目抽样。
3. G5c不重开；首轮原件缺失如实记录；同步差异单列。

R19保持原终态；没有基于本审查批准R20坐标、许可或新研究运行。正式资格/G6/G7未因本轮工程回归绿色而完成。

## 七、核对的固定来源

全部GitHub路径均读取于上述HEAD，原始工具读取可在聊天引用定位。

- branch endpoint：最新SHA、时间及直接parent。
- `stage2_6_1/report/route_c_stage2_6_1_admission_regression_evidence_v3.md`
- `stage2_6_1/src/rl_curriculum/curriculum261_r17_admission_substance.py`
- `stage2_6_1/runner/r21_full_collection_regression.py`
- `stage2_6_1/runner/r21_sync.sh`；candidate→HEAD比较。
- `stage2_6_1/artifacts/repair17/development/admission_regression_evidence_v3_closure/full_regression_20260925/{summary.json,regression_evidence_v3_record.json,execution.stdout.txt}`
- `stage2_6_1/report/route_c_stage2_6_1_r20_research_design_v2.md`
- `stage2_6_1/report/r20_research_design_calc.py` 与对应JSON。
- `stage2_6_2/report/route_c_stage2_6_2_g5c_verification.md` 新增第6节。

方法参照（不是项目运行证据）：pytest官方API参考的收集钩子说明；statsmodels `ztost` 的正态等效性定义。所有数字纠错由本附件独立脚本在明确假设下计算。
