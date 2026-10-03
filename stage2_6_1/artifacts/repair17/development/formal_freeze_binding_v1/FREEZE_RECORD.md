# FREEZE_RECORD — formal_freeze_binding_v1(Commit A 冻结记录)

任务: RouteC_FormalFreeze_ApprovalBinding_v1(FLP R4 CLOSED PASS 之后
的最终冻结与批准绑定轮)。本文件进入 Commit A 本体;按任务约束,
Commit A 的最终 SHA 只能在提交产生后读取,**本文件不含也不预测
Commit A 自身 SHA**(无自引用);后续证据以独立 evidence HEAD 引用
真实 Commit A。

## 基线(实读)

- 仓库: ceyirelehe47/freqai-rl-platform-audit,分支
  route-c-stage2-6-1-repair17。
- R4 代码/回归候选(祖先,已验): `04d1020800794df35bd1618f9b3ffb0d21d63adf`。
- R4 证据树(Commit A 的直接父,开工时本地=远端 HEAD):
  `c3cba8b20ebd1633be05c9858c9db7ebeca7e6e9`。
- 开工未提交面(在飞,零触碰): porcelain 计数
  `{"??": 277, "D": 1, "M": 6, "T": 9}`(2026-10-03T18:46:13Z 快照)。

## Commit A 冻结面(本提交新增的全部文件)

相对父 `c3cba8b2`:**零 src/零 tests/零 runner 变更**,仅新增本准备
目录下列文件(逐文件 SHA-256,提交前实算):

| 文件(相对本目录) | bytes | sha256 |
|---|---|---|
| README.md | 2044 | e26666542b65acf4b28ba2ea7f26ddce5cd016757975de581fbead4e0089eb2a |
| FREEZE_RECORD.md | 本文件 | 提交时以本文件字节为准(不自哈希) |
| scripts/snapshot_protection_surface.py | 7162 | 4d488ce779692f3d42967bb5d1a773b375f866b3b4dfd82a4229a685f616d009 |
| provenance/gate_topology_reconciliation.json | 6433 | 9af551752d6b2989f4e9c09855fb421b05f90a1a7e972713e2753a01cd1102ff |
| provenance/gate_topology_reconciliation_digest.txt | 74 | cde2b72a08e62f9a2a54438da53c2bcbdb9b9067dff67cb11d4e7e04f70cc189 |
| protection_surface/before.json | 12635 | 338f5fc7cd2fd572f5f5705e15f5b5780d04faad48aa523ba1fae0e317925f5b |

## 链外来源证明(先于 Commit A 锁定)

- 入口: `rl_curriculum.curriculum261_r17_cli provenance-lock`
  (WSL 部署树解释器 `/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python`,
  PYTHONPATH=部署 src;release repo 经 `/mnt/f/trading/freqai-rl-audit`
  读取历史 Git blobs)。
- digest: `r17gtrec-3112e5deb863a810392bbaae0e4e21d9f7017c97d0fd172d6e66eb6551bf4e9d`
  (write 一次锁定;隔离目录 provenance-verify 复算一致,输出见
  evidence HEAD `evidence/provenance_consumer_isolated/`)。
- 未向历史正式根覆写;未重跑任何历史科学实验;纯 Git blob 读取。

## 未来部署映射(本轮只验证映射与字节,不安装)

A 链外部前置位置 = 未来受信任部署根的 A artifact 根下
`gate_topology_reconciliation.json`(R17_EXTERNAL_ARTIFACTS 合同;
链步 1 provenance-verify 将重算 digest 比对;缺失/漂移即链死于
第 1 步)。批准后的正式激活按已冻结字节安装并核验;本轮不创建该
正式位置、不创建任何会话。

## 冻结语义

- Commit A 之后仅允许文档/证据提交(evidence HEAD);A 的冻结面
  (上述文件 + 全部 src/tests/runner 既有内容)不得变化。
- 若冻结后代码或合同发生实质变化,必须形成新候选、重新核验并
  显式作废旧待批身份;不得 amend A、不得 A′ 偷换。
- 本轮不签发许可、不启动正式研究/训练、不激活 formal_ready、
  不创建生产运行实例(见 protection_surface/before.json)。
