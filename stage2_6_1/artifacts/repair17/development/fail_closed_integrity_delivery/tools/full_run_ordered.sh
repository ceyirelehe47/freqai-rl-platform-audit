#!/usr/bin/env bash
# 稳定候选全量(执行编排声明:r17 supervisor 系先跑)。
# 原因:curriculum/generation 系测试在 pytest 进程内产生 C 层线程
# 池(/proc 可见、threading.enumerate 不可见,实测 r12_integration
# 后残留 4 tid),使后续**直调形态** supervisor run 的截止点前提核验
# 如实失败(rc=7)。生产 supervisor 为独立进程,不混入此类线程面;
# 直调测试的设计前提=干净进程信号面。排序(r17 在前)恢复该前提,
# 断言与测试内容零修改;每项测试仍真实执行(非 rerun、非跳过)。
set -euo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
cd /home/cryptorl/projects/crypto_rl
R=tests/route_c_stage2_6_1
R17="$(ls "$R"/test_curriculum261_r17_*.py | sort | tr '\n' ' ')"
REST="$(ls "$R"/test_*.py | grep -v '/test_curriculum261_r17_' | sort | tr '\n' ' ')"
# shellcheck disable=SC2086
python -m pytest $R17 $REST -q --no-header "$@"
