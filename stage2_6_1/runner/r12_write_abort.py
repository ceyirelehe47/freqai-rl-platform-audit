# -*- coding: utf-8 -*-
"""R12 诚实 FAIL 的 abort 写入(§25:机械引用原始失败,禁手工改写数值)。

失败事实(源:calibrate 通过后 lock-plan 崩溃的原始 traceback):
- 阶段:正式 qualification plan lock(cmd_lock_plan)
- 异常:KeyError: 'bundle_hash'
- 位置:curriculum261_r12_cli.py 第 1717-1721 行(calibration_bundle_hash
  = json.loads(preprocessor_bundle_calibration.json)['bundle_hash'])
- 实际键:preprocessor_bundle_hash(artifact 由 cmd_calibrate 写入)
- Commit A:75a66dde368c6f7c8ccc1a70e19445a6f86165fe(冻结代码含此缺陷;
  继承自 R11 复制路径,R11 未到达 lock-plan;R12 rehearsal 的合成
  payload 路径未覆盖真实 artifact 读取——工程覆盖缺口,如实披露)
"""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

from rl_curriculum.curriculum261_r12_namespaces import (
    qualification_r12_exposed,
    r12_iteration_aborted,
    write_r12_iteration_aborted,
)

REASON = (
    "正式 lock-plan 阶段源码缺陷:cmd_lock_plan 读取 "
    "preprocessor_bundle_calibration.json 的 'bundle_hash' 键,实际键为 "
    "'preprocessor_bundle_hash'(KeyError: 'bundle_hash';"
    "curriculum261_r12_cli.py:1717;Commit A 75a66dd 冻结代码)。按 §5 硬"
    "规则:Commit A 后任何源码缺陷(含 artifact reader KeyError)不得修复"
    "后继续;不存在 A′。R12 永久结束,下一轮必须 R13。calibration main/"
    "holdout 已独立 PASS;final qualification 未执行;exposure 未写入;"
    "cue audit/global K audit/tail integrity/design 全部 PASS(正式结果保留)。"
)

if __name__ == "__main__":
    write_r12_iteration_aborted(REASON)
    print("aborted:", r12_iteration_aborted())
    print("exposed:", qualification_r12_exposed())
