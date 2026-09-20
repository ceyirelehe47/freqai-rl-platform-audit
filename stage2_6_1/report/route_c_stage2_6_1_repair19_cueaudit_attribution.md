# R19 cue-audit 统计 FAIL 的定量归因(只读材料,非处置建议)

- 锚: artifacts/route_c_stage2_6_1_repair19/cue_contract_audit.json
  (终端态原件;本文件只重算/解读其数值,不改任何原件)
- 用途: 为 R20 处方提供精确量级;处置权属外部审查方。本轮(R19)
  已按合同终态,不存在救援解释。

## 失败叶子的精确量级

| 量 | 值 |
|---|---|
| analytic p_contract | 0.950432 |
| model 语料(block-cluster bootstrap, 20000 重抽样, 12982 事件/500 簇) | mean 0.949237, SE 0.001861, CI95 [0.945558, 0.952843] |
| validation 语料(12965 事件/500 簇) | mean 0.945931, SE 0.001941, CI95 [0.942102, 0.949672] |
| analytic vs model | z = +0.64(双尾 p=0.52;一致) |
| **analytic vs validation** | **z = +2.32(双尾 p=0.020)**;超出 CI95 上界 0.000760 = **0.39 SE** |
| 语料间差(model − validation) | 0.003306, z = 1.23(两语料彼此无显著差异) |
| MC(10⁶ 事件)vs analytic | z = −0.82(analytic 自身 MC 一致) |
| 双语料合并 recall | 0.947585(25,947 事件;naive 二项 SE 0.001384,簇结构使有效 SE ↑) |

## 结构性事实(与数值同样重要)

1. `analytic_weights_source = "model corpus 正 cue 位置直方图"`:
   解析权重取自 **model 语料自身**的 cue 位置分布——model 语料与
   analytic 的部分一致性是结构内置的;**validation 是唯一独立检验面**,
   恰是它在 2.32 SE 处未过。若 validation 的位置分布相对 model 有
   微小系统偏移,该结构会把偏移全额计入"analytic vs validation"
   的缺口(model z=0.64 / validation z=2.32 的不对称与此相容)。
2. 三路闭合的其余叶子(MC |diff| 0.000179 / once-vs-attempts 逐位
   / k_mean / aggregate 重算 / tail / global-K)全部通过——FAIL 是
   单叶子、边界性(0.39 SE 超界)的。
3. once-vs-attempts: validation 500/500 块一次通过、零拒绝——
   语料生成无 rejection 筛选效应。
4. **双语料 cue 位置分布实测差**(原件可复算): TV 距离 0.0741、
   274 个位置的逐点最大 |Δp| = 0.0019(t=84;其余大偏差点
   Δ≈0.0015-0.0018 分散于 t=4/6/84/190/200/269)——分布差异
   存在且非单点;它对 analytic(model 锚定权重)与 validation
   实测率之间缺口的贡献量级,可由审查方按 q(t) 原件精确复算。

## 两种相容读法(量级事实,不是处置)

- **边界涨落读法**: 双语料彼此 z=1.23 不显著;单语料 |z|≥2.3 的
  边际事件在两次独立抽取中并非极端;0.39 SE 超界处于"换一次独立
  抽取可能通过"的量级。
- **小系统分量读法**: 合并 25,947 事件的 recall 低于 analytic
  ~0.0028(簇结构校正后 z≈1.7);且 analytic 权重的 model 语料锚定
  (事实 1 的锚定分量已被下方决定性对照定量排除;剩余为语料实现率
  本身的小偏低)。

**决定性对照已执行(本报告作者,只读重算)**: 以 validation 锚定
与双语料合并直方图为权重源重算 analytic —— p 分别为
0.950438 / 0.950435(对照锁定值 0.950432,移动 ≤ 0.000006 =
缺口的 −0%);z(validation) 在任何锚定下均 ≈ +2.32。原因:
analytic_terms 的 q(t) 跨位置近恒定(≈0.98862),权重源不改变
期望值。**结论:权重锚定伪影被定量排除**——事实 1 的结构性
担忧不构成缺口来源;剩余区分只在「validation 抽取的边界涨落」
与「语料级小系统分量」之间(事实 2/合并量级 z≈1.7 一如前述)。

## 历史抽取散布的真实机制(第二增补修正版,含实证)

初版曾把历史散布解读为"计划锚定的逐 run 独立重抽"——**机制表述
错误**,现以直接实证修正:

1. **固定代码下 audit 完全确定**。在 HEAD(7bbb033) 工程坐标重跑
   正式机械面(`r17_cli cue-audit`;determinism/provenance/audit
   前置后):计划 digest 仍为 r15ap-0da8dc45fe38,corpora 逐位
   复现正式运行——p=0.950432、model=0.949237、validation=
   0.945931、z=+2.32、FAIL 原样再现。r10 机械面另证:同代码
   7 次重抽全同(r10ca-4b98b06f)。plan payload 无 run 级熵;
   corpus 派生 = f(plan digest, 固定 namespace/attempt/rng)。
2. **散布仅存在于代码状态之间**:audit 计划 digest 含代码身份,
   三次互异历史值对应三个代码状态:

| 代码状态(计划 digest) | z(model) | z(validation) | validation 判定 |
|---|---|---|---|
| r15ca-5c79cb…(12 次 rt run 所在状态,彼此逐位同) | +1.18 | **−0.79**(0.951915) | 过 |
| r15ca-6782f9…(rt 20260917T101918Z) | +1.31 | **+0.68** | 过 |
| r15ap-0da8dc…(正式与 HEAD 复现,同一状态) | +0.64 | **+2.32**(0.945931) | **不过** |

3. **R20 含义(比初版更精确)**:
   - 原样重跑**不重抽**——逐位复现 FAIL(已实证);
   - 新抽样需要改变 audit 抽取坐标(代码身份变化,或处方中显式
   的新 audit 坐标/namespace),不是"再跑一次";
   - 三个代码状态值为 ±2 SE 量级的实现散布,与"边界性"量级一致;
     model z 三态全正(+0.64/+1.18/+1.31)的方向性观察保留,
     仅三态,不构成结论。

(工程重抽证据:部署树 r17_audit_redraws/draw_head 等;只读分析,
未触碰任何正式 design/semantic namespace 与 admission 面。)

## 复核路径

```
python3 - <<'PY'
import json
d=json.load(open("…/route_c_stage2_6_1_repair19/cue_contract_audit.json"))
p=d["p_contract"]; m=d["direct_generator"]["model"]["block_cluster"]
v=d["direct_generator"]["validation"]["block_cluster"]
print((p-m["point"])/m["se"], (p-v["point"])/v["se"])
PY
```
