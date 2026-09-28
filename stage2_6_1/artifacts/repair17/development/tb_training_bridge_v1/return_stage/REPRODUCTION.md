# 复现与执行环境

## 环境

- WSL CryptoRL-Ubuntu-24.04;conda `freqtrade-rl`
  (Python 3.11.16/pytest 9.1.1/pluggy 1.6.0);
- 部署树 `/home/cryptorl/projects/crypto_rl`(单一合并 src/tests;
  vendor pin `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`);
- 仓库(组装视图)`F:/trading/freqai-rl-audit`,branch
  `route-c-stage2-6-1-repair17`;同步 = cp 改动文件到部署树
  src/tests 对应路径;runner 镜像于部署树根
  (`eng_training_bridge_v1.sh`)。

## 端到端工程运行(候选 C)

```bash
# 部署树(已同步候选 C 的 8 个 src 文件与 2 个测试文件)
bash /mnt/f/trading/freqai-rl-audit/stage2_6_2/runner/eng_training_bridge_v1.sh
# 或部署树根: bash ~/projects/crypto_rl/eng_training_bridge_v1.sh
```

步骤与 rc:fixture v1/v2 构建 → eng-input-lock(正例)→
eng-route-check(v2)→ G01 formal 拒绝(expect rc=2)→
eng-run(E01+E02)→ eng-cold-read(E03)。全部 rc 见
`ENG/eng_run_rcs.txt`。

注意:重复执行将消耗固定数据集重放配额(账本上限 2 次)与
optimizer smoke 配额(8 次/2048 步);reviewer 复验请共用
`ENG/ppo262e_quota_ledger.jsonl`。

## 单测

```bash
cd ~/projects/crypto_rl && source activate-freqtrade.sh
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1
python -m pytest tests/route_c_stage2_6_2/test_ppo262e_qualified_input.py \
                 tests/route_c_stage2_6_2/test_ppo262e_env_bank.py -q
# 38 passed(零原生生成、零 optimizer)
python -m pytest tests/route_c_stage2_6_2 -q   # 204 passed
```

## 全收集回归(261;R17-first)

launcher:`TB/tb_training_bridge_v1_launcher.sh`(monitored entry,
commit-a=803fe66e,产物 `TB/full_regression_v1/`)。
