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
  (事实 1)使 validation 的缺口可能含真实的位置分布偏移分量。

区分两读法所需的信息(审查方裁量): 位置分布差异已实测(事实 4,
TV=0.0741);决定性对照 = 以非 model 锚定的权重源(如解析先验或
双语料合并直方图)重算 analytic 的口径差。

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
