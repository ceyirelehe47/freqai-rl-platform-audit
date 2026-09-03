# Stage 2.6.1 Repair R12:Dependence-Aware Global Cue-K 审计 + 不可变实现冻结 + 一次性 Clean Qualification

**最终判定:FAIL(诚实 FAIL;下一轮必须 R13)**

- 分支:`route-c-stage2-6-1-repair12`
- 基线:`96446f2f91cd13df0411dc70909dd43ab8864046`(R11 Commit B)
- Commit A(Implementation Freeze):`75a66dde368c6f7c8ccc1a70e19445a6f86165fe`
- 失败阶段:正式 `lock-plan`(qualification plan lock)
- 失败原因:`KeyError: 'bundle_hash'`(curriculum261_r12_cli.py:1717;
  实际键 `preprocessor_bundle_hash`)
- 失败性质:Commit A 冻结代码中的潜伏源码缺陷(artifact reader 键名
  不匹配);按 §5 硬规则不得修复后继续,不存在 A′
- final qualification:未执行;exposure 未写入;全部正式 R12 namespace
  已封存(abort 后拒绝访问)

---

## 1. 五十二问

### 治理与冻结

**1. R11 为何在 Commit A 后已经失去 clean-chain 资格?**
R11 的 Commit A(`df0292a`)之后,第一次正式 audit 暴露
`PRIOR_R9_PARAMETER_PACK_DIGEST` 手工转录错误,随后修改
`curriculum261_r11_cli.py` 并提交 A′(`572c509`)再继续同一 iteration。
按 R11 任务合同,Commit A 后发现任何源码缺陷即必须结束;A′ 的出现
本身即 clean formal chain 失效的机器证据(R12 以 git
`merge-base --is-ancestor` 链绑定:A 是 A′ 祖先、A′ 是 B 祖先)。

**2. 为什么 R12 不允许 A′?**
R10/R11 连续两轮出现"正式 audit 才发现低级源码错误"后靠 A′ 续命。
§5 明确:Commit A 后任何源码/测试/依赖/vendor/config 语义修改——
即使只是键名、参数、typo、KeyError——R12 永久 FAIL,下一轮必须
R13。本轮 lock-plan 的 KeyError 正是触发该条款的情形。

**3. R12 如何在 Commit A 前运行真实 release rehearsal?**
`release-rehearsal` 子命令(冻结前工程):两次完整 `cmd_audit` 处理
路径(临时目录)、cue-audit plan build/lock/load/verify、code-freeze
writer、historical bindings、baseline ancestry、vendor、依赖解析、
signature/AST audit、namespace guards、design plan roundtrip(真实
build/lock/load + 重复锁拒绝)、abort writer、path-cleanliness
writer、report loader;第二次验证幂等读取与重复写入拒绝;全程真实
代码路径,零 monkeypatch。结果 PASS。**如实披露其覆盖缺口:
rehearsal 的 design-plan roundtrip 用合成 calibration 数值,未覆盖
cmd_lock_plan 对真实 calibration artifact 的键名读取——这正是本轮
失败逃过 rehearsal 的原因(见 §52)。**

**4. baseline ancestry 如何验证?**
`HistoricalEvidenceBinding-v1`(curriculum261_r12_historical):
`git merge-base --is-ancestor 96446f2 HEAD` + `merge-base ==
expected` + 分支名/fork point + R11 提交链(A→A′→B)blob 级完整。
正式 audit 重算(不信 manifest 自报),PASS。

**5. 历史 digest 如何避免手工转录?**
R11 及更早的 digest 常量链保留(继承);R12 新增的全部 R11 证据绑定
改用 git blob 身份(`git hash-object` vs `git rev-parse <rev>:<path>`)
与 `git show` 读取,源码不新增任何手工转录的文件级长 digest。

**6. R11 t=226 为何不是 tail?**
episode n=288 的最后 24 bars 从 t=264 开始;t=226<264。R12 合同
`tail_definition.t226_is_tail=false`,正名为 position-wise
mirror-count distribution failure。

**7. 旧 4σ gate 的具体统计问题是什么?**
三重问题:(a) 约 250 个位置 cell 各自承担 4σ 硬门禁,family-wise
错误率未校准(名义 Bonferroni 只是上界且按独立近似);(b) 同 block
相邻位置事件共享 source 随机单元(单 gap 互斥),聚合统计量方差
不能用独立 event 公式;(c) 31 事件格点结构下 |z|=4.0005 越线属格点
抖动,连续正态硬阈值在边界不稳。

**8. 真实底层 mirror-hit 随机单元是什么?**
每 (corpus, block, source bar s∈[1,n-17]) 的 paired_noise gap 抽签
G_u~U{8..16}(顺序消耗同一 PCG64 流;iid)。

**9. event 之间存在哪些共享 source 相关性?**
同 block 内相邻事件候选窗口重叠共享单元;单 gap ⇒ 每 unit 至多命中
一个事件(互斥 ⇒ 负相关)。聚合 cell 方差 = Σq(1-q) < 独立公式
Σw²p(1-p)(实测 var_ratio=0.8889 的共享案例验证)。

**10. attempts acceptance 是否依赖 K?**
否。结构接受(c2_structural_issues + pair 合同 + cross-rung
matching + integrity)只读 hidden 结构表(cue_dir/s/w ±1 状态、A/B
共享表、参数差异面),不读噪声值/mirror hit/K/cue 检出 ⇒ 条件固定
incidence graph 只重采样 gap 的 null 合法(预注册于合同 payload)。

**11. 新 global statistic 是什么?**
T_obs = max_j |Z_j|,j 跨 model/validation 的 position cell +
corpus aggregate + true-tail aggregate(共 527 个合格 cell);
Z_j=(S_j-μ_j)/σ_j,μ=Σq、σ²=Σq(1-q),q_u=n_u/9。

**12. cell eligibility 如何预注册?**
仅依据 cue schedule/candidate graph/null 信息量:exact null variance
>0 且唯一下层单元 ≥30;禁止依据观察到的 K 偏离(R11 的
"min_events=30" 不再承担门禁)。

**13. model 和 validation 如何纳入同一 family-wise gate?**
两 corpus 的全部合格 cell 进入同一 max 统计量与同一联合 null。

**14. null joint distribution 如何生成?**
固定依赖结构(事件坐标/块归属/incidence),逐 replicate 对全部单元
重采样 gap(先 model 后 validation 的固定 draw 模式),镜像落点匹配
事件;保持 mirror 边界与 attempts 语义。

**15. global alpha 和 Monte Carlo continuation 是什么?**
α=0.05;第一层 B=50,000,对 tail exceedance 概率取 99%
Clopper–Pearson 区间:下界>0.05 ⇒ PASS,上界<0.05 ⇒ FAIL,跨线 ⇒
同 stream 续至 200,000(前缀 chunk digest 逐位一致;换 seed/重置/
丢弃前缀即 fail closed);仍跨线 ⇒ INDETERMINATE=FAIL。

**16. R11 旧数据在新 global gate 下结果是什么?**
T_obs=4.000504(仍为 model/position/t=226);530 cell;p_global=
0.0526589;CP99=[0.0501002, 0.0552653];tier1 下界 0.0501>0.05 ⇒
PASS。R10:p=0.5169(T=3.2312);R9:p=0.4795(T=3.2636),均 PASS。

**17. 为什么该结果不改变 R11 FAIL?**
§2/§13:R11 FAIL 永久,不得重解释/conditional PASS/追认/撤销;
重分析仅用于 method development 与回归;且禁止据此调整 R12 的
alpha/eligibility/B/statistic/tail 定义(R12 合同在重分析落盘后、
正式数据前锁定,digest 链可证)。

**18. 新方法的小图 exact validation 结果?**
n=32、事件 [9,10,11]、3 单元(unit 1 服务 3 事件)共享设计:729 组合
全枚举的 μ/σ² 与解析矩逐一相等(<1e-9);randomization 标准化
|mean_z|<0.03、|var_z-1|<0.10;exact global p 与 randomization 频率
一致。早期草稿的权重式聚合矩(Σw·Bernoulli(1/9))被该枚举直接
否定并修正为 Σq(1-q)——§14.1 的价值所在。

**19. null calibration 结果?**
60 次正确 null 全局检验,经验拒绝率 5/60≈0.083,在 α=0.05 的二项
99% 上界内 ⇒ 不过度拒绝(global_k_null_calibration.json)。

**20. injected bias 验证结果?**
source hit 概率偏移 +8%(24 块):p=6.66e-04 拒绝;特定位置过度命中
(t=60):p=3.33e-04 拒绝(global_k_injected_bias_validation.json)。

**21. true tail boundary audit 结果?**
TailMirrorBoundIntegrity-v2(确定性 hard gate,独立合同):model 793
+ validation 801 个 tail 事件,候选界/越界/primary/replay 逐位一致,
PASS;R12 正式数据 legacy 旁证 max|z|=3.2329(model t=244)/3.0572
(validation t=248),远低于 4.0。

**22. Generation Evidence 是否完整且 fail closed?**
是。GenerationEvidenceCompleteness-v1(orchestrator 治理层重算):
preplan 168=168、shadow 792=792(40 blocks)、正式 calibration 全部
对齐,0 问题;missing/duplicate/orphan/accepted 唯一性/block attempt
log 均进入 stage PASS。生成层 recorder 保持纯观察(R11 冻结语义)。

**23. 两次 cold shadow 是否一致?**
是。ledger 身份 digest 相同,33 个 artifact 剥离非身份字段后 0 差异
(修复 ledger_source 路径字段后以冻结代码全新重跑 B 再比较)。

**24. full supervised release rehearsal 是否完整执行?**
是。正式 3 model seeds(20270111-13)× W/B/U × [128,128] MLP × 三族
× main/holdout:W/B 各 3/3 distinct seeds,无 NaN/Inf,标签对齐零
失败,distinct-seed gate 机械复算;development evidence only。

**25. Commit A SHA 是什么?**
`75a66dde368c6f7c8ccc1a70e19445a6f86165fe`。

**26. Commit A 后是否有任何源码变化?**
无。`verify_r12_code_freeze` 全程零漂移(drift/added/removed 全空;
最终复验在 abort 之后仍 pass=True);真实 `git status` 0 修改
(checkout 输出的 M 行为 CRLF 归一化记账,非内容漂移)。

**27. 正式 cue audit 结果?**
PASS。plan digest `r12ap-7f67dc…`;p_contract=0.950442;MC=0.950392
(diff 0.00005≤0.001);model 0.951131 CI[0.947523,0.954689]、
validation 0.951176 CI[0.947385,0.954913] 均含解析值;recall floor
0.930442;once/attempts 一致(bitwise 50 块);exact replay ≤1e-12;
aggregate 复算一致。

**28. global K p、区间、B 数量和 verdict?**
T_obs=3.2329(argmax=model/position/t=244);527 cell;
p_global=0.511770;CP99=[0.505991, 0.517528];B=50,000(第一层
下界已 >0.05,无需二层);verdict=PASS。

**29. 是否 indeterminate?**
否。

**30. design 是否解锁?**
是(cue audit PASS 后)。

**31. 三个 candidate 结果?**
c2l_historical_control / c2l_conservative / c2l_midpoint 全部完整
评估(40 matched blocks main+validation × 全部 n∈{10,15,20});
qualified_combinations=2。

**32. selected candidate 和 n?**
机械选择(最小 n → maximin → 参数距离 → id):**c2l_historical_control,
n=15**(maximin=0.106280;param_distance=0.0;非预设——R12 全新
seed space 的机械产物)。

**33. independent marginal 结果?**
design_r12_independent_marginal(每 rung 20 pairs):PASS
(D0>D1>D2>D3、D3>0、三语义 AND、point recall≥0.90 护栏)。

**34. parameter pack digest?**
`r12pk-c021cc6a45bc114fe869fe94ea2a61e77b16f58861464dcf445dc81950eadd9d`。

**35. main/holdout preprocessing 结果?**
PASS。calibration_r12→v2_main、calibration_holdout_r12→v2_hold 各自
独立 fit;role/namespace/manifest/parameter-state/bundle 哈希全验;
互换拒绝;无隐式全局 preprocessor。

**36. canonical/scaled equivalence 结果?**
PASS。canonical vs scaled action/return equality=100%,0 unexplained
mismatches(main+holdout+shadow 覆盖)。

**37. supervised main/holdout distinct-seed 结果?**
main:W/B 各 3/3(三族);holdout:W/B 各 3/3(三族);U 仅诊断;
单 seed 不得重复计数(R11 B2 语义保持)。

**38. calibration main 是否独立 PASS?**
是(preprocessing/supervised/curriculum/routing/generation evidence
全部独立)。

**39. holdout 是否独立 PASS?**
是。

**40. 是否使用 pooled rescue?**
否(main_holdout_independent.pooled_rescue_used=false)。

**41. final plan digest?**
未产生——lock-plan 在构建 plan payload 时崩溃(KeyError),plan 未锁定,
无 digest。

**42. sealed preflight 是否零 final seed?**
未到达(final plan 未锁;preflight-static 已 PASS,sealed preflight
未执行;qualification 相关 namespace 从未被访问,seed 派生=0)。

**43. exposure 何时写入?**
从未写入(qualification_r12_exposed()=False;marker 与 ledger 均无)。

**44. final 执行几次?**
0 次。

**45. final core/independent/semantic 数量?**
不适用(未执行;合同目标:core=80+4n、independent=80、semantic=160
blocks/1280 episodes)。

**46. final verdict?**
不适用(未执行)。R12 迭代级 verdict = FAIL(lock-plan 源码缺陷,
§5/§8.4 硬规则)。

**47. PPO smoke 结果?**
未运行(§24:final FAIL 后不得运行;不得作为补救)。

**48. full-cold 结果?**
未运行、未宣布(§24)。

**49. C3 PPO Branch D 是否仍开放?**
是(继续开放;本轮未触及)。

**50. Stage 2.6.2 正式状态?**
FAIL(此前已定;R12 不改变;亦不自动开始任何后续阶段)。

**51. R12 最终 PASS/FAIL?**
**FAIL。**

**52. 若 FAIL,下一步是否需要结构调查而非换 seed?**
本轮失败是**工程缺陷**(冻结代码的键名错误),不是统计/结构问题——
统计侧全部 PASS(cue audit/global K/tail/design/calibration main/
holdout)。下一轮 R13 不需要 cue-noise 结构调查;需要的是:
(a) 修复 `bundle_hash`→`preprocessor_bundle_hash` 键名;
(b) 把 cmd_lock-plan 的**真实路径**(读取真实 calibration artifact)
纳入 pre-freeze release rehearsal 与 preplan full-pipeline rehearsal
——本轮 rehearsal 用合成数值绕过了该读取,是覆盖缺口;
(c) 对全部尚未被真实数据执行过的正式 CLI 路径(lock-plan/preflight-
sealed/qualify 的 artifact 读取面)做一次真实-键名对拍 rehearsal
(可用已生成的 calibration artifacts 做只读 dry-run)。
R13 必须在全新 namespace 重做正式链(audit→…→final)。

### 治理细节补充

- **R11 保留**:R11 abort marker/cue plan/event trace/结果 blob 与基线
  逐位一致(r11_abort_binding PASS);R11 namespace 未复用;历史文件
  零修改。
- **legacy 4σ**:R12 正式数据 binding_gate=false、legacy_diagnostic_
  only=true;R11 重分析 legacy z 精确复现 4.000504000506。
- **abort artifact**:r12_iteration_aborted.json 从原始失败机械生成
  (traceback sha256 固化于 lock_plan_failure_traceback.json;
  next iteration=R13);fail_path_cleanliness.json 由冻结代码的机械
  writer 生成(source_changed_after_freeze=false、exposure=not_exposed、
  design plan=locked、calibration=executed、pooled_rescue=false)。

## 2. 执行时间线(机器可查)

1. Commit A `75a66dd`(冻结;两次 shadow/release rehearsal/supervised
   rehearsal/determinism/114 测试全绿后)
2. 正式 audit(freeze 锚定 Commit A;ancestry/R11 binding PASS)
3. 正式 cue-audit(plan `r12ap-7f67dc…`;全局 K PASS)
4. plan-roundtrip(14 项全过)
5. design-plan-lock(`r12dp-cfbf0f…`)
6. design(选 c2l_historical_control n=15;pack `r12pk-c021cc…`)
7. calibrate(main+holdout 全 PASS;robustness gate PASS)
8. preflight-static PASS
9. **lock-plan:KeyError('bundle_hash')→ R12 FAIL**
10. abort marker + 失败证据 + fail_path_cleanliness
11. Commit B(本提交:仅 artifacts/raw logs/报告/结果索引)

## 3. 与失败无关但已完成的正式价值

- C2MirrorCountGlobalAudit-v1 全链(合同→小图枚举→校准→偏置→
  正式 527-cell PASS)首次给出 dependence-aware family-wise 的
  mirror-count 分布证据;
- R11 t=226 之谜闭合:legacy 4σ 的拒绝在正确校准下不成立
  (p=0.0527,贴线),R11 数据本身无结构异常;
- calibration main/holdout 在全新 seed space 独立 PASS(W/B 各 3/3
  distinct seeds)——首次到达该里程碑的 repair 轮次。
