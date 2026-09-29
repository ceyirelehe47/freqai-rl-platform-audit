# RouteC_QualifiedInput_TrainingBridge_v1 独立审查

## 0. 结论与身份

**结论：NOT_CLOSED_ENGINEERING / 本轮未通过独立终验。**

不是研究统计 FAIL，不否认真实工程 PPO 烟测已经发生，也不重新打开 R25 已结项分支。需要修复的是本轮消费侧的实际路由、输入/缓存/模型绑定、异常配额记录，以及补齐本轮 reviewer 的既有独立原件。

- 任务基线：`5ac420a1e6eb50ddd55f0a2969f4cf4ff2b3560a`。
- 最终业务候选 C2：`e565298dad8063df70775dfdd47e3bf682f29926`。
- 本次实时读取的远端 HEAD：`c85eee4e34c044f95de075bcafe8c88934172ce5`。
- 实际上传 RETURN：SHA-256 `ec803bee6ed46c975d45888859b9d452c21177dbf4401640516ceda953b00c38`，892,095 bytes。
- 全局默认无单轮 8 小时上限的补充仍有效；取消时间上限不取消原生生成、optimizer 配额、监护或独立 reviewer 要求。

## 1. 实际做了什么；没有做什么

### 1.1 包与记录

独立打开最终 ZIP，检查 93 普通文件、92 条内部 SHA 精确覆盖、CRC、路径/类型/大小写重复；全部通过。未修改上传原件。

13 个候选源文件的实际 SHA-256 均与包内 source manifest 相符。又通过 GitHub 独立取得核心四个模块的 blob 身份，与包内整文件计算结果一致：

| 模块 | Git blob |
|---|---|
| ppo262_qualified_input.py | `4775b00f0b68e170254d108404ed7a7702271b99` |
| ppo262_eng_profile.py | `a10604b5cfa7fe1c31b4670401c4fb1bc3566e13` |
| ppo262_banks.py | `04971dceb269d1d54fd65cab624647e33ab22475` |
| ppo262_cli.py | `a57c40f5e06dac0b64a7c6b264f171de34539f4d` |

不把这四个模块的远端对拍扩大表述为全部 315 个部署模块的新一次核验。其余候选文件已做包内摘要对拍；完整部署身份属于原回归/reviewer 声明的证据范围。

四份 JUnit 已逐 testcase 解析。261 两轮均 2541=2534 passed+7 skipped，0 failure/error；262 两轮均 204 passed。261 的 collection 与 JUnit 多重集一致，record 的原始文件摘要引用核对一致。首轮 launcher rc=3 的失败身份保留；第二轮 rc=0 绑定 C2。详见 `validation/REGRESSION_RECORDS.json`。

没有再次在用户 WSL 跑全回归，也没有在助手本地运行整套项目测试。缺少 gymnasium、SB3、datasieve/用户部署环境；对此没有伪造兼容环境或改版本。

### 1.2 真实模型只读复核

从模型 ZIP 中用 `torch.load(weights_only=True)` 读取 policy/optimizer tensor 状态，没有反序列化其中的任意 Python callable，没有调用 learn。

- 内部 `num_timesteps=256`、`_total_timesteps=256`、`n_steps=256`；`n_epochs=10`。
- Adam 参数状态 step=40，参数均有限。
- 根据真实 tensor 重算的参数摘要等于 `eng_ppo_smoke.json` 的 after 摘要。
- 独立按保存的 MLP 权重重算 32 个冻结观察，确定性动作完全一致。
- 本地 torch 2.10.0+cpu 与原 WSL torch 2.13.0+cu130 不同，概率最大差约 5.96e-8。本次不把跨版本手工前向冒充原 WSL `eng-cold-read` 的 1e-9 合同复验，不把这个环境差异判为项目 FAIL。原件报告的同环境冷读残差为 0。

因此模型不是空文件，真实优化后的参数状态有实物证据。报告中的“1 次 optimizer update”应理解为一次 PPO `train()` 调用记录；原生 Adam step=40，与 10 epochs×4 minibatches 相容。这一术语澄清不是阻塞项。

### 1.3 分支反例的方法边界

`probes/reproduce_bridge_boundaries.py` 默认执行完整归档的输入锁、bank、profile、CLI 源码，未改其目标判定函数。外部 WSL 环境身份及 V2 装载被隔离成“已知有效记录”的受控依赖：V2 依赖只接受原有效 envelope 字节，环境身份采用该夹具已有的身份；这不是原生 V2 数值重跑，也不是证明真实部署状态。

生成测试在候选实际 `param_recorder` 钩子处停止，冷读反例在 `PPO.load` 边界停止。模型加载边界到达不被写作“完整冷读 PASS”。全部原生 episode/研究生成、fit、新 optimizer 更新均为 0。

脚本提供 `--native-project <WSL project>` 以在真实环境复现同一目标分支；应由主 Agent/reviewer 运行后保存原始结果。不要把本地替身依赖改成 validator 恒真；真实复现必须用公共装载器。

本轮 16 个组件用例中 7 个符合预期、9 个暴露漏检/检查路径缺失。这个计数是用例数量，不是“发现九个彼此独立缺陷”。详见 `probes/RESULT.json`。

## 2. 阻塞 B1：六类入口报告不等于实际路由（M02，关联 N01）

`ppo262_eng_profile.py::route_profile_inputs` 读取 qi 参数后，手写一个包含 smoke/config_dev/probe/core/dev_eval/final 的字典。`cmd_eng_route_check` 把这个字典写盘并直接打印 pass=true。

它没有调用或设置这些实际消费者；原来的 `_locked_plan/_locked_rung_params/_locked_reference_thresholds` 以及 config/probe/core/dev-eval/final 命令仍绑定 R2。新 eng-run 与 eng-cold-read 存在，不等于其他新 profile 路由已经接通。

**反例 `route_report_no_consumers`：**将五个被宣称覆盖的实际消费者替换成一旦调用就记录并停止的哨兵，执行完整 eng-route-check CLI。返回 rc=0、宣称六类入口，消费者调用计数为零。这个测试本身不证明需要运行教学预算；恰恰证明应在真实参数解析/消费者边界验证，而不是验证同一个报告字典。

原 NEXT_GOAL §3.1/§4 与 M02 已明确要求真实组件边界。仅将报告降级为“方案”不能满足本轮必需实现项。

**修复标准：**让新 profile 的真实消费入口共享已验证输入上下文；可以薄适配，也可以公共解析器，但必须是后续实际调用点会使用的实现。实际 config/probe/core/dev-eval/final 入口在 generator/训练/评估之前放哨兵，无需执行高预算。破坏其中任一消费者的输入来源必须使对应检查失败；旧 R2 默认保留。

**N01 相关缺口：**现有 `test_n01_planted_same_seed_not_possible` 只是枚举并验证正常样本没有交集，没有植入碰撞。装载器也没有读取与校验输入所声明的完整 qualification/fit/calibration/holdout seed 面。`declared_fit_training_namespace_overlap` 把计划 fit_namespace 改成实际 train namespace并重算工程 plan/绑定，仍可装载；这说明声明、bundle 来源与消费范围未联动验证，不证明当前真实样本已经串用。

将新输入实际来源与训练/评估范围纳入公共隔离检查，并明确对“手工 fit 标签、不派生随机 seed”的处理；不能以“它不在旧白名单中”当作检查成功。必须有真正注入相同派生值/相同来源的拒绝对照。

## 3. 阻塞 B2：输入来源和已验证缓存仍可失配（I01/I02/I03）

### 3.1 来源/终态关联未完整核验

`load_qualified_input` 仅检查 result.source_iteration 非空，没有与 plan.source_iteration 比较；exposure 检查格式/计划/完成/one_shot，没有与源/训练迭代关联。

- `source_iteration_mismatch`：只把 result.source_iteration 换成另一个来源，计划、计划摘要、授权锚保持原值；装载仍通过，所有 checks=true。
- `exposure_iteration_mismatch`：只换 exposure.iteration，同样装载通过。
- `missing_producer_identity`：移除计划 code_identity.producer 并在隔离工程夹具中一致重算外层绑定，装载仍通过。共同契约检查主要检查 family version/observation version/声明型 contract digest，不能以这些版本标签代替被要求的来源与共同执行语义证据。

工程夹具允许构造，不等于它可以内部互相矛盾。这里没有绕过正式 admission，也不声称正式训练被非法解锁；formal 空注册表这层防线仍存在。

**修复标准：**核对 plan/result/exposure/源身份的实际关联；针对 Cq/Ct 不同提交而共同语义等价的合法正例允许通过，针对共同 generator/环境行为改变但版本号未更新必须拒绝/明确验证，不能简单改成 commit 必须相等。

### 3.2 快照只有“不可变约定”，没有消费时保护

`QualifiedInput` 把字典和 preprocessor 直接存入可变对象；`rung_params()` 深拷贝返回值是正确的局部保护，但并未保护缓存本身。`generate_eng_bank` 只做 isinstance，然后直接用 qi.rung_params()，不重算原已验证 pack identity。

- 合法 v2 控制在 bank 参数钩子观察到 C1 D1 `opp_drift_bps=45.0`。
- 修改 `rung_params()` 返回副本不影响缓存，控制通过。
- **`bank_cached_pack_mutation`：**装载后将缓存 `_pack` 内该值改为 999；保存的 pack digest 不变，实际重算已不符。调用原 bank 链仍在 param_recorder 处观察到 999，未拒绝。

这是原任务明确要求的缓存污染测试，不是声明 Python 可以防御任意恶意内存写。应通过真正不可变/隔离持有对象，或消费边界重验绑定，防止正常可达缓存污染；同字节移位与安全深拷贝仍须通过。preprocessor 和 authorization/contract 的可变引用也要一并按同一策略检查，避免只修 _pack 一处。

## 4. 阻塞 B3：冷读未核验声称绑定的全部对象（M01/E03）

`cold_read_checkpoint` 在 PPO.load 前比较模型文件 SHA、四个 qi 字段(plan/pack/bundle/profile)和消费模块身份。保存 manifest 中的来源、授权绑定、bank/seed/预算等字段，没有相应消费检查。模型冷读成功的正例证明权重可读，不证明这些未被消费的绑定有效。

**原冷读函数的受控边界用例：**
- 正确输入/原 manifest 到达模型加载边界，符合预期。
- pack digest 错误在加载前拒绝，证明既有防线正常。
- 改 qualification_source_iteration，或删 authorization_binding_digest，仍到达模型加载。
- 改 bank namespace/keys/count/hash，并把 model_seed 改为 123、steps 改为 2048，仍到达模型加载。

未执行假模型前向，不将“到达模型加载”写成完整 cold-read PASS。源码中加载之后只有对冻结观察的概率/动作对拍，没有补做这些身份检查。

**修复标准：**明确可信 manifest/输入身份的绑定边界，消费时验证原要求中的完整输入锁、来源、bank/seed/profile、预算与共同代码契约；必要字段缺失或错配不能只因为模型 ZIP SHA 正确就继续。固定观察原件本身也应与保存时身份绑定，不能让它变成可自证的报告。正常旧证据不改写；需要兼容旧工程 checkpoint 时明确版本与已核验迁移，不把旧 manifest 重签成新运行。

## 5. 阻塞 B4：失败/中断未计入 optimizer 配额（P01）

原任务取消的是 8h 总时长，不是 8 次/2048 步配额。`engineering_ppo_run` 在 learn 之前仅检查剩余额度，直到 learn、保存、冻结观察全部成功之后才 append ppo_smoke。异常路径没有开始记录或 finally 收尾，进程中断更无记录。

`probes/reproduce_quota_interruption.py` 对原 QuotaLedger/engineering_ppo_run 函数体做隔离控制流测试，learn 处注入异常（没有真实 env/optimizer 运行）：9 次调用异常均留下 0 runs/0 steps，下一次仍可通过额度检查。正常已记账 8×256 的控制则拒绝下一次。

此结果不是发现用户实际上额外训练了 9 次；它证明异常路径不满足“失败与中断同样计数”的要求。

原生生成账本另按固定 len(keys)=6 记录候选数，`generate262_pair` 内真实 attempt 重试没有反馈实际计数；本轮原件为 first-pass，不能据此证明重试路径计数正确。

**修复标准：**开始前保留可核验预约/运行身份，实际步数/attempt 过程中累积或可恢复，成功/失败/中断均终结；未确认进度保守保留，不当作零消费释放。用隔离小型故障注入证明即可，不重训、不新建通用资源平台。

## 6. 必需交付补件：reviewer 原始检查脚本与输出

93 成员包含 REVIEWER_CONTENT_REPORT.md，但没有该报告引用的 tmp_reviewer_tb_v1 的 probe#1/#2/#3 独立脚本、43 项断言原始输出，以及 reviewer 重放/冷读的原始记录。包外回执和文字报告不能替代这些原件。

RETURN_REQUIREMENTS §2 与 RUNBOOK §5–6 已要求随包交付。请从已有审阅目录原样纳入；没有的如实说明，不能重建成当时原件或倒填时间。此处不质疑确实调用过 reviewer，也不要求平台未提供的后端模型元数据。

## 7. 本轮接续方式（必须传给主 Agent 与 reviewer）

1. 继续同一 TrainingBridge 任务返修，不重开 R25，不重跑旧 11 坐标/G5c，不启动正式研究/资格/教学。
2. 默认无单轮 8 小时上限；保留单作业监护、数据/优化器配额以及用户停止权。
3. 主 Agent 修复与基础自测后，必须实际委派已配置的 OMP `reviewer`，配置模型 `zhipu-coding-plan/glm-5.3-flash`；先把原任务/本报告/全部失败上下文交给它。不能自签，也不因过去 reviewer PASS 而跳过本轮复验。
4. Reviewer 必须检查真实消费者，而不是只读 eng-route-check 字典；逐条复现本报告反例，并提供合法对照。不要为了找 PASS 换 reviewer，不递归委派。
5. 本报告的组件反例可零新增原生生成、零参数更新。账本已登记 bank replay=2/2、成功=12/12、smoke=2/8、steps=512/2048；不能因返修清零。
6. 可只读复用确有原件的已有 bank/模型与手工合成 fixture。若新候选端到端验证确实需要新的原生重放，而无既有 bank 原件可复用，先报告该具体配额阻塞并取得明确追加授权；不得偷偷第三次生成。剩余 optimizer 配额不等于原生 bank 配额增加。
7. 源码修复形成新候选，执行适用 261/262 回归和定向验证；不复制旧回归当新候选 PASS。报告/打包修订只验相应面。
8. 内容全部通过后再封 RETURN，由 reviewer 对最终字节冷读，签包外回执；附上独立检查脚本、真实输出、失败原件。最终仍由 ChatGPT 独立终验，不代签 CLOSED PASS。

## 8. 证据索引

- `validation/PACKAGE.json`：最终 ZIP 冷读。
- `validation/SOURCE.json` / `SOURCE_REMOTE.json`：包内源文件摘要与核心远端 blob。
- `validation/REGRESSION_RECORDS.json`：JUnit/collection/原始引用计数。
- `validation/WEIGHTS.json`：实际 checkpoint tensor、Adam 状态及独立前向。
- `probes/RESULT.json`：16 个受控组件用例。
- `probes/QUOTA_RESULT.json`：异常配额控制流用例。
- `probes/reproduce_bridge_boundaries.py`：可在 WSL 使用真实依赖复现（有明确零生成/零模型加载哨兵）。
- `probes/reproduce_quota_interruption.py`：明确合成的中断账本测试。
- `probes/history/`：本地审查脚本初版与修正记录；其中 setup 错误不计为候选缺陷。
- `raw/`：本次上传包的只读解包原件。

上述反例不证明旧 WSL 运行实际串用数据、泄漏进程或超预算；它们说明当前新增实现与“全矩阵 PASS”的结论不相符。
