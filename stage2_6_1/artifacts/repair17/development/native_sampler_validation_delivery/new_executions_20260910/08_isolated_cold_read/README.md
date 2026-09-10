# 08_isolated_cold_read：真实隔离冷读（新执行）

日期：2026-09-10。这是新执行，不替换已归档的 04/07 输出，
不声称先前已经隔离；历史缺口（07 首次 check/stdout 被覆盖）如实保留。

- 驱动：任务包 r17_native_evidence_closure_review/verify_isolated_cold_read.py（一次性验收驱动，非生产补丁）
- 命令：source ~/projects/crypto_rl/activate-freqtrade.sh 后
  python .../verify_isolated_cold_read.py --package <BASE>/originals/04_full2_pkg
- 环境：WSL CryptoRL-Ubuntu-24.04，cryptorl 用户，Python 3.11.16（未升级）
- 包内自测：10 passed, 0 failed, 0 skipped（真实 user/mount namespace）
- 正式结果：WORK_DIR=/tmp/r17_true_cold_ewbs6e7v，整体 rc=0
  - isolation_rc.txt=0；isolated_result.json overall_ok=true
  - 四案例 healthy/missing/append/same_length rc=0/1/1/1，payload 全部不变
  - 反例拒绝原因均为 telemetry_win 必要字节缺失/不符（FileNotFoundError / 233496->233548 / 同长度 SHA 变化），非 import 或环境错误
  - isolation_proof.json：父子 mount namespace 不同，/mnt 与 /home/cryptorl/projects 两探针 before/after 均 FileNotFoundError
  - source_after.json：源包字节不变
- outer_run.log 为最外层执行控制台记录
- work_r17_true_cold_ewbs6e7v/ 为 WORK_DIR 原样副本：driver.py、plan.json、
  configs/（四份派生配置）、cases/（四份测试副本）、mountinfo.txt、
  isolation_proof.json、isolated_result.json、isolation_rc.txt、
  results/（四场景 command/stdout/stderr/rc/verified）、source_after.json

固定审查 HEAD：5aea0bf4581130cd4d10d5567612fe368c42c2c2（候选 29101e0）。
未重跑 pytest 全量，未启动采样器，未改停止协议，未修改旧记录与锚。
