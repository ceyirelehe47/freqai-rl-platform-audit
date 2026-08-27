# 阶段 2.6.0e 报告:Null 经济摩擦、功效证明与 Pack 完整性最终闭环

- 阶段:2.6.0e(独立审查修复轮;基线 91ce3b0 = 阶段 2.6.0d)
- 结论:**PASS**(等待独立审查;不自动进入 2.6.1)
- 日期:2026-08-27
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / vendor freqtrade @ 52bc96f(clean)

## 一、修复的四个审查问题

### 1. 经济摩擦与冻结账本不一致(工作包 A)

旧公式 `1 - (1-fee)^2 * (1-slippage)^2`(fee=0.001 时 0.001999)把"卖出按名义额扣费"
误当成"买卖各打一次 (1-fee) 折",与冻结 LongFlatLedger 的真实语义不一致。

新单一实现来源 `src/rl_curriculum/null_friction.py`(null-friction-contract-v2):

```
retention = [(1 - f) / (1 + f)] × [(1 - s) / (1 + s)]
friction  = 1 - retention
fee=0.001、slippage=0 时 = 0.002/1.001 = 0.001998001998...
```

- margin 单位与 `EpisodeResult.net_return` 相同(simple return);
- margin 不大于冻结账本真实摩擦(构造上相等);
- price_tick 保守下界性质由**真实执行函数**实证:`friction_parity_problems()`
  在预注册网格(7 价格 × 6 tick × 5 fee × 4 滑点,可采纳组合 665 组 ×
  市场卖出/终端清算两条路径 = 1330 次真实 LongFlatLedger 往返)上验证
  tick=0 精确相等、tick>0 实际摩擦 ≥ closed-form;该校验进入
  `verify_spec_payload`(任何 qualification spec 构建都强制通过,不是注释);
- 摩擦合同哈希 nfc- 进入 spec 的 margin_derivation → 实现变化即旧承诺失效;
- 旧公式在数值、公式字符串、spec 校验三个层面被测试明确区分。

qualification spec 升级 `null-qualification-spec-v2`(v1 显式拒绝)。

### 2. power analysis 未中心化 + 只覆盖 Always Long(工作包 B)

`null-power-analysis-v2` 全部重做:

- **中心化(B1)**:`sample = resample(empirical − mean(empirical)) +
  target_absolute_edge`;target 成为真实的绝对经济优势。报告逐场景记录
  原始经验中心/残差中心/target/tolerance/超出量/模拟样本中心;
- **明确目标场景(B2)**:预注册 `POWER_SCENARIO_MANIFEST`(进入 spec hash,
  npss-):valid_zero_edge / inside_half_tolerance / boundary_diagnostic /
  violation_plus_1x_margin(target = 容差 + 1×margin)/ violation_plus_2x_margin;
  "1×margin 拒绝功效" = 超过允许容差一个完整 margin 的违规优势;
- **四块全部进入硬门(B3)**:always_long_vs_flat / oracle / rule_trend /
  high_turnover_vs_flat,targets_met 覆盖每个 family × block × 场景;
- **零方差场景(B4)**:解析确定性分支(stochvol oracle 恒 flat),不标记
  skipped,仍计入 required coverage(54 个 required 场景全部在);
- **保守置信界(B5)**:Wilson score 双侧 95%(坏率取上界/好率取下界),
  不用点估计;MC 次数由精度需求定为 1600(HFT 容差 0 的边界检验名义
  误判率 ~2.5%,400 次 MC 的 Wilson 上界噪声会越 5% 线;已按精度需求提高);
- **cluster 重新校准(B6)**:预注册阶梯 32/64/96/128,两层规则(升序):
  (a)该档全部功效硬目标(Wilson 界);(b)该档 namespace 前缀上三族四块
  经济等价检验通过——只满足 (a) 但前缀资格 INSUFFICIENT 的档位不得选用。
  实测:32 档功效目标已满足但 sign/volstate 前缀 32 的 long 块 CI 上界
  (+0.00324/+0.00269)超过 margin → 不可选;64 档两层全过 → 选定 64,
  与冻结 MIN_QUALIFICATION_CLUSTERS=64 一致;
- bootstrap 以向量化实现,索引流与 `paired_bootstrap_ci` 逐位一致
  (parity 测试强制;单次完整 power ~90s,重验证有可信缓存)。

### 3. 正式执行器不重跑 power report(工作包 C)

`src/rl_curriculum/null_power_reverification.py`:执行器在加载候选
checkpoint 前,从承诺绑定的完整报告 payload 重建 spec,用当前代码
**确定性重跑完整 power analysis**,重算 npa- 哈希对账,重派生
targets_met(与承诺摘要逐项比对),核验场景清单/MC 配置/比例置信方法/
cluster 数/代码哈希。public summary 不再是信任源。

可信缓存:键覆盖 spec hash/family 报告哈希/power code/generator 实现/
EvalConfig/timeframe/duration/MC 配置/场景清单;命中后仍验证内容哈希
(篡改缓存 → 重跑)。实跑:首考 37s,幂等重考 11s。

14 类攻击(C4)全部 EXAM_INVALID(测试 + artifact 双层证据)。

### 4. pack antithetic 完整性降级(工作包 D)

`null-pack-validity-v2`:

- **D1**:每 seed 恰好 (orig, flip) 各一(按 Episode 计数,非 flags 集合):
  缺一/多一/两条同 flag/≥3 条/重复 spec 全部 PACK_INVALID;
- **D2**:pair 参数一致性(family/version/seed/timeframe/resolved
  duration/行数/除 flip 外 params/实现指纹);
- **D3**:物化路径镜像验证对**每一对实际绑定的 pair**执行:逐步 log return
  反对称(容差 1e-12)、绝对收益一致、pair 累计 drift 抵消(1e-9)、
  volume 逐位一致、hidden volatility/regime 路径逐位一致、时间戳一致、
  特征可由价格因果重算;预注册容差进入报告哈希;
- **D4**:nuisance 对称性——生成器侧 `antithetic_flip` 不再进入 nuisance
  counter-hash(与 derive_seed 对称),同一 pair 的 nuisance 槽位逐位一致;
  validator 对实际物化 Episode 强制 bitwise 校验;
- **D5**:Oracle/Rule 恢复与 AlwaysLong/HFT 相同的完整硬门
  (中心 ≤ tolerance 且单侧 CI 上界 ≤ tolerance);实际 mock pack 以完整
  检验通过(oracle/rule/long 的 CI 上界最高 +0.00149 < margin 0.001998),
  不依赖降级;
- **D6**:npb- 升级为真实 builder manifest(null-pack-builder-manifest-v1):
  绑定 assemble_mock_hidden_pack(builder 函数)/qualification_seeds/
  pack_construction_seeds/pack_order_seed/attempt 循环/匿名拒绝日志/
  validate_null_pack/参数规范/family 列表/pair 数量;签名不得含
  candidate/checkpoint/model/policy(fail closed);修改 builder 或
  validator 任一 → npb- 变化(测试证明)。

11 类 antithetic 负例(多 flip/多 original/缺 flip/重复 spec/参数/
timeframe/duration/非镜像路径/hidden/volume/nuisance)全部 PACK_INVALID。

## 二、协议升级(工作包 E)

| 协议 | 旧 | 新 |
|---|---|---|
| sealed commitment | v4 | **sealed-exam-commitment-v5**(v1-v4 显式拒绝)|
| null qualification report | v3 | **null-qualification-v4**(v1-v3 拒绝)|
| qualification spec | v1 | **null-qualification-spec-v2** |
| power analysis | v1 | **null-power-analysis-v2** |
| pack validity | v1 | **null-pack-validity-v2** |
| builder manifest | — | **null-pack-builder-manifest-v1**(新增)|
| exam CLI | v5 | **hidden-exam-cli-v6** |

语义未变不升级:checkpoint-manifest-v3、training-attestation-v1、
candidate-runtime-manifest-v1、sealed-exam-context-v3、六项冻结合同。
新执行器明确拒绝:v4 及更早承诺、v3 及更早资格报告、
null-power-analysis-v1、null-pack-validity-v1、validator-only npb-、
旧摩擦公式 spec(artifact:legacy_v4_material_rejection.json)。

## 三、mock sealed exam v6 全链路(工作包 F)

```
冻结账本摩擦合同 parity(1330 次真实往返)
→ Spec v2 → 三族 64×16 family 资格(全 QUALIFIED)
→ 中心化四块 power v2(阶梯选 64;54 required 场景全覆盖)
→ mock null pack(每族 32 pair;每对镜像/nuisance 逐位验证;四块硬门)
→ builder manifest(npb- 绑定真实 builder)
→ issuer + 受信 runner + 256-step PPO smoke + sidecar + attestation
→ sealed-exam-commitment-v5
→ 正式执行器重跑完整 power analysis(npa- 对账)   #1 FAIL 37.2s
→ pack validity 现算对账(含 pair 镜像)
→ 系统级沙箱加载候选 → G4/Null/反作弊 → smoke 正常 FAIL
→ 幂等重试 #2(11.3s,同结果)→ --detailed 披露退休 #3
→ 全部篡改矩阵(power 14 类 / antithetic 11 类 / v5 承诺 / legacy)
```

256-step PPO 仍只用于 provenance/接口/沙箱/协议闭环;不声称完成课程或 G4。

## 四、关键数值

- 正确 friction:0.001998001998...(0.002/1.001);旧公式 0.001999 已废除
- qualification margin:= friction(simple-return 单位)
- selected minimum cluster count:64(两层规则;32 档因前缀资格不充分被排除)
- 四块功效(family×block 全过,Wilson 界):
  zero-edge false-INVALID 上界 ≤ 5%、violation+1x 拒绝功效下界 ≥ 80%、
  violation+2x false-QUALIFIED 上界 ≤ 5%
- required scenarios:54/54 完整,skipped = []
- 三族 family qualification:sign / volstate / stochvol 全 QUALIFIED
  (long 块 CI 上界 +0.00108 / +0.00149 / +0.00107 < margin)
- actual pack:PACK_VALID;96 对 antithetic pair 全部镜像通过
- builder manifest hash:npb-397b55a9…;power report hash:npa-1cdf2a58…

## 五、测试与回归

- 新增 tests/route_c_stage2_6_0e/(8 文件 + conftest):109 项全过
- 全量回归(2.5 → 2.6.0e 全部阶段):见 regression_test_summary.md
  (零失败、零跳过、零 xfail)
- 冻结合同未修改(RouteCEnvCore-v1.0.0 等六项);vendor/freqtrade
  clean @ 52bc96f
- 未开始正式 C1/C2/C3 PPO 课程训练

## 六、仍存在的已知限制

1. cluster 阶梯 >64 的候选(96/128)在 64-cluster 经验基座下不可评估
   前缀资格(需先扩展生成);本阶段 64 已被两层规则选定,未触发;
2. power 重验证的可信缓存位于评估方运行环境(项目 .cache);缓存只是
   加速,键与内容哈希双重校验后仍等价于重跑;
3. 正式私有 builder 的 manifest 在评估环境对实际 builder 重算;公开
   仓库只含 mock builder 与 manifest 结构;
4. parity 网格的"价格低于一个 tick"组合按预注册可采纳性规则排除
   (该配置下执行合同本身 fail-closed,不构成可交易市场);
5. HFT 零优势场景的名义误判率 ~2.5% 是容差为 0 时单侧 97.5% 检验的
   边界固有率(非缺陷);MC=1600 使 Wilson 上界稳定低于 5% 硬目标。

## 七、Artifacts

`artifacts/route_c_stage2_6_0e/`(17 类 JSON + 完整性记录),公开目录
`stage2_6_0e/`(report/src/experiments/tests/artifacts/logs)。
