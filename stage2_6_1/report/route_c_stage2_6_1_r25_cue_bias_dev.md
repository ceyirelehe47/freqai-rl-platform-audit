# R25 Cue 偏差开发研究(RouteC_CueBias_DevelopmentStudy_v1)结果报告

日期:2026-09-26。任务:`RouteC_CueBias_DevelopmentStudy_v1`。
代码候选:`617b61ac89400f2fc9261b51c1e9a420fe08f016`(初始候选
5849acc + 计划同步修正;见 §5)。研究计划(数据前冻结):
`artifacts/repair17/development/r25_cue_bias_dev/plan/dev_plan.json`,
digest `r25dp-54841c4f731a46c00bc61d89b1c1baa6e2f54d11f7cc6e05554310cb7eaaca63`。

## 1. 研究问题与固定设计

问题:冻结生成器/sentinel/检测规则/解析参考下,新 validation 语料
的平均 recall 与固定参考 P0=0.950431552876822 相差多少?

固定设计(数据前):11 个开发坐标(c01..c11,名称/顺序/block index/
RNG/预算全部先登记);每坐标 model 500 blocks(once)+ validation
500 blocks(first_pass attempts,max_attempts=5 整 block 重试);
统计原子 = canonical D0/A 正 cue unique event,matched block 为
cluster;单坐标 SE = 原实现 block-cluster bootstrap(20,000 次,
seed 20270102);主聚合 = delta 等权平均,S_raw=sqrt(sum s_k^2)/K,
倍率 r_analysis=1.5 实际进入 CI90(delta_bar±z_0.95×S_analysis,
alpha=0.05);开发报告分界 ±0.003(非正式容忍度);分类用已接受
v4 `classify_primary`(planned_k=11)。

未运行项显式 NOT_RUN(非 PASS):MC 1e6、global-K audit、tail
integrity、非劣效 gate、cue-contract audit pass 判定(本轮为
开发估计研究,非正式审计)。

## 2. 执行

- 工程入口:`runner/r25_cue_bias_dev_entry.py`(plan-create/
  run-coordinate/cold-read);开发 namespace 28 个显式枚举接入
  `CURRICULUM261_SEED_NAMESPACES`(api;守卫不接受任意字符串,
  正式资格名单零变更)。
- 工程 smoke:s1/s2(各 4+4 blocks,once_bitwise ok),名称与
  11 研究坐标不重;数据永不计入研究。
- 受监护批次(外层 run `20260926T132814_7514_448`,engineering,
  business_rc=0;1 次 progress_stall 告警为坐标切换间隙误报,
  已逐坐标核实在跑):11/11 坐标按固定顺序完成并逐坐标封存
  (SEALED 成员哈希);总耗时 ≈50 分钟(远低于 45min/坐标上限)。
- 每坐标 validation 全部 first_pass(attempt_histogram {"0":
  500}),零结构性重试;once-vs-attempts bitwise 检查 11/11 ok。

## 3. 主结果(冷读,只读复算)

冷读从封存事件原件重算每坐标 recall/SE(封存成员哈希、block
覆盖 500/500、事件身份唯一性全过,零完整性问题),再以 v4 主入口
分类。另做独立第三方复算(3 坐标 recall 逐位相等 + 聚合 CI 一致)。

| 坐标 | recall(validation) | delta_k=P0−recall | SE |
|---|---:|---:|---:|
| c01 | 0.951026 | −0.000594 | 0.001990 |
| c02 | 0.947096 | +0.003335 | 0.001923 |
| c03 | 0.948411 | +0.002020 | 0.001918 |
| c04 | 0.951823 | −0.001391 | 0.001763 |
| c05 | 0.951547 | −0.001115 | 0.001823 |
| c06 | 0.950193 | +0.000239 | 0.001950 |
| c07 | 0.951999 | −0.001567 | 0.001833 |
| c08 | 0.949010 | +0.001421 | 0.001900 |
| c09 | 0.949177 | +0.001254 | 0.001866 |
| c10 | 0.950262 | +0.000169 | 0.002001 |
| c11 | 0.953526 | −0.003094 | 0.001715 |

主分析(planned_k=11,r_analysis=1.5 实际进入区间):

- delta_bar = **+0.0000615**
- S_raw = 0.000568;S_analysis = 0.000851
- **CI90 = [−0.001339, +0.001462]**,完全落在 ±0.003 开发分界内
- 幅度类别:**within_equivalence_bounds**
- 方向:not_resolved(区间跨零;点估计微正 = 实测平均略低于
  P0 约 0.006 个百分点,但方向未解决)
- r_analysis=1 对照(预标明,不参与结论选择):同判 within;
  方向 not_resolved。

各坐标局部 p_contract(诊断,不参与主统计):0.95037..0.95045,
与 P0 差 ≤0.0002;主 delta 全部使用同一固定 P0(D06)。

## 4. 解释与边界

- 在本轮开发设计的条件下,证据**不支持**存在超过 ±0.003 的可
  重复系统偏差;单坐标 delta 有正有负(最大 +0.0033/c02、
  −0.0031/c11),与随机涨落量级一致。R19 的公开负结果
  (validation recall≈0.94593)低于本轮全部 11 个新独立坐标的
  观测范围 [0.9471, 0.9535],更接近一次抽取的尾部波动;但本
  轮不构成对 R19 原件的复核或改判。
- 实测单坐标 SE(≈0.00190)与 v4 规划锚 s=0.001941 同量级,
  r_true≈0.98,处于规划表 r_true≤1.5 的设计前提内。
- 本结论是**条件开发结论**:冻结代码闭包、固定解析锚、独立
  坐标与正态近似假设;±0.003 不是生产容忍度;不追认 R19 PASS,
  不修改任何正式 audit/qualification 合同,不授予正式资格或
  训练许可。R19 终态、R24 CLOSED PASS、C 限定接受均不变。
- 下一步建议:若需要正式判定,基于本轮信息设计正式校准审计
  (机制定位无强信号,正式路线应先评审解析锚与生成机制是否需
  要更精细的误差预算),由外部独立审批;本轮不发起。

## 5. 候选与回归

- 初始候选 5849acc 的首次受监护全量(run 20260926T115245_9843_
  1046):执行全绿 2484 tests/0 failed/0 errors/8 skipped,但执行器
  rc=3 `regression_skip_ids_outside_allowed_table`——第 8 个 skip
  是 R25 计划冻结断言在部署树的结构性 skip(计划未同步)。
- 修正候选 617b61a(计划同步进部署树;研究数据此前未生成,计划
  digest 不变):受监护全量(run 20260926T123944_0473_1024)GREEN
  ——**2484 tests / 0 failed / 0 errors / 7 历史 skip,两段 rc=[0,0],
  ok=true**,record v6 sha `7295ccda…da2e7d`,verify
  (collection 2484 / static 2003 / files 147)。+14 = 本轮新增
  R25 工程测试(13 跑 + 1 原结构性 skip 现真跑)。
- 部署树与候选字节经 r21_sync 同步核对;定向面(namespace 治理
  51 项 + R25 入口 13 项)全过。

## 6. 原件

- 研究批次:`study/coord_c01..c11/`(每坐标 manifest/SEALED/
  model_events.jsonl/validation_events.jsonl/model_block_seeds/
  validation_block_attempts/summary;含 attempt 日程、选中身份、
  事件级 trace 全量)。
- 冷读:`study/cold_read_result.json`。
- smoke:`smoke/coord_s1、coord_s2/`(工程验证,不计入研究)。
- 回归:`full_regression_20260926_v1`(首跑拒发证)与
  `full_regression_20260926_v2`(GREEN)全目录。
- 监护原件:`run_supervision/runs/20260926T115245_9843_1046/`、
  `20260926T123944_0473_1024/`、`20260926T132814_7514_448/`
  (含全部 required 成员)。

## 7. 状态

开发研究完整出口达成(11/11 坐标、既定主区间、如实类别),
交付待独立验收。R19/正式资格面不变;无下游训练;不自动升级
为正式结论。
