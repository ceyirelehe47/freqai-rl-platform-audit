# R17 准入 v2 实质绑定:代码身份 vs 实验计划内容的职责边界

- 依据: 2026-09-20 工程指令("核清 code tree digest 与真实实验计划
  digest 的职责;不能把代码身份核验写成已经完成实验计划内容绑定")。
- 对象: `curriculum261_r17_admission_substance.py`(签发/消费唯一
  同源实现);本澄清只**明确既有合同语义**,不改变任何验证行为、
  格式或阈值,与 R19 终态/R20 处方无关。

## 澄清内容

准入 v2 的 substance 检查含两块相互独立的绑定:

| 块 | 完成的绑定 | **不**完成的绑定 |
|---|---|---|
| plan_digest 实算(`git rev-parse <commit_a>^{tree}` 复算比对) | **代码身份**:准入所指代码 = Commit A 的 git tree(preregistration 已把 plan_digest 口径定义为该 tree digest) | **实验计划内容**:不验证计划文档/参数与审查方所见一致,不验证 tree 内任何计划文本哈希 |
| 回归证据核验(junit 元素级 + sha256 + commit_a 绑定) | **回归绿**:该代码身份上的全量/差分回归证据真实性 | 与计划内容无关 |

实验计划内容的约束由**另外的合同**承担,与准入互不替代:

- design 侧 plan-lock(计划锁定 digest,如 r15ap-/r15dp- 系);
- 链上 provenance-lock / gate topology reconciliation;
- 预注册文档自身的评审流程。

## 结论(防误读的一句话)

"plan_digest == Commit A tree digest" 证明的是**跑的代码没换**,
不是**实验计划内容已被绑定**;两者在准入 v2 中前者受验、后者
明确不在本模块职责内。任何把前者表述为后者的措辞均为越界,
以本文件与模块 docstring「职责边界」节为准。
