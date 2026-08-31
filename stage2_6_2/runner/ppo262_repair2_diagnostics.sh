#!/bin/bash
# s262_diag_r2_1 诊断命令序列(WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl)
set -e
cd "$(dirname "$0")/../../.."   # 项目根(本仓库为组装视图,实际运行于工作副本)
source activate-freqtrade.sh
export PYTHONPATH=src
CMD="python -m rl_curriculum.ppo262_r2_cli"
$CMD namespace-integrity
$CMD baseline-integrity
$CMD plan-lock
$CMD evaluator-validation
$CMD gradient-verify
$CMD supervised
$CMD scratch
$CMD bc
$CMD family-decision
$CMD semantic-validation
$CMD summary
