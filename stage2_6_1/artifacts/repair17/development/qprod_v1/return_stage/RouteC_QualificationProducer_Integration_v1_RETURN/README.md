# RouteC_QualificationProducer_Integration_v1 RETURN — 复现说明

最终代码候选: C7 = `cda4e975e8db16a75d485c27708847a878622a59`
(分支 route-c-stage2-6-1-repair17)。候选链:
C1=e956c61a(实现)→C2=501bfd84→C3=af39a89f→C4=d77a616f→
C5=280ca805→C6=f1bebc37→C7=cda4e975(F1-F4 修复);证据 E1..E6,
远端 HEAD=4ee81535(Windows git ls-remote 实测,git_receipts/)。
基线 d910409a(TBv1 E7,CLOSED PASS 工程范围,不重开)。
正式运行决定页:`route_c_stage2_6_1_qprod_v1_readiness.md`。

## 1. 环境与同步

WSL CryptoRL-Ubuntu-24.04;部署树 `~/projects/crypto_rl`;解释器
`/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python`。

```bash
# 仓库 → 部署树(261+262 src/tests + runner;逐文件 tr -d CR)
wsl -d CryptoRL-Ubuntu-24.04 -- bash -c \
  "tr -d '\r' < /mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/qprod_sync.sh | bash"
```

## 2. 零数据组件测试(85 项,无原生生成)

```bash
wsl -d CryptoRL-Ubuntu-24.04 -- bash -c "cd ~/projects/crypto_rl && \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -m pytest \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_context.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_permit.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_plan.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_coordinate.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_aggregate.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_levela.py \
  tests/route_c_stage2_6_2/test_ppo262_qprod_export.py -q"
```

## 3. 完整回归(绑定 C7)

```bash
# 261 全收集(R17-first/auditor/lifecycle;证据 v6 采集)
wsl -d CryptoRL-Ubuntu-24.04 -- bash -c \
  "bash ~/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh engineering \
   --max-seconds 5400 -- \
   /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
   ~/projects/crypto_rl/stage2_6_1_runner/r21_full_collection_regression.py \
   --repo /mnt/f/trading/freqai-rl-audit \
   --commit-a cda4e975e8db16a75d485c27708847a878622a59 \
   --deploy-root ~/projects/crypto_rl \
   --out-dir <持久目录>"
# 262 全套
wsl -d CryptoRL-Ubuntu-24.04 -- bash -c "cd ~/projects/crypto_rl && \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -m pytest \
  tests/route_c_stage2_6_2 -q --junitxml=<out>/junit.xml"
```
本包原件:regression/full_regression_v6(summary ok=true,
2614/0/0/7)+ regression/regression_262_v3(240 passed rc=0);
失败中间轮(v2/v4/262_v1)原件保留在同目录 *_failed_original。

## 4. E01 原生坐标烟测(配额 2/2 已用满;复核请勿第三次重放)

原生原件:engineering/native_smoke_run1 与 native_smoke_run2/
(逐坐标 cue_contract_audit.json、cue_event_trace.jsonl、
qprod_block_seed_log.jsonl、raw_episodes/ df+hidden CSV、seal、
qprod_quota_ledger.jsonl)。零生成只读复算:

```bash
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/qprod_v1/native_smoke_run2
wsl -d CryptoRL-Ubuntu-24.04 -- bash -c "cd ~/projects/crypto_rl && \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
  stage2_6_1_runner/qprod_level_b_entry.py aggregate \
  --base-dir $BASE --authority-dir $BASE/authority && \
  /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
  stage2_6_1_runner/qprod_level_b_entry.py cold-read \
  --base-dir $BASE --authority-dir $BASE/authority"
```

## 5. E02/E03 Level A 排练→导出→消费冷读(零原生生成)

```bash
wsl -d CryptoRL-Ubuntu-24.04 -- bash -c \
  "tr -d '\r' < /mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/qprod_e02_levela_e2e.sh | bash"
```
原件:engineering/level_a_e2e/(C7 复跑;formal_log_verification
sequence_ok=true;delivery_*/ 六件套+receipt;formal 拒绝记录)。

## 6. 正式运行就绪清单与待批决定

见 `route_c_stage2_6_1_qprod_v1_readiness.md`。真实正式资格/研究/
K=11 正式抽样/训练 NOT_RUN;新增 optimizer/BC/PPO 更新=0;TB 旧账
未动;部署正式许可/状态/更新计数=0。
