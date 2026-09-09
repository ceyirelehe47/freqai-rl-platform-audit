# 自实现路线（v5）留档与路线切换说明

## 背景

上一份任务书《Stage2_6_1_R17_C3_Entry_Resolution_Temp_Ownership_Agent_Implementation.md》要求
Agent 自行实现两个工作包（PPC-PATH-ENTRY / PPC-PATH-ERROR / PPC-TEMP-OWNER）。Agent 在收到
交接包《R17_Receipt_Implementation_and_Agent_Test_Pack.zip》之前，已按该任务书完成：

- 阶段一：接手版 reader（git blob `93d0172b6428b1710ebc21900247473b5a4d3e64`）三反例复现
  （`counterexamples/old_reader_counterexamples_v5.json`，三例 reproduced=true）。
- 阶段二：自行实现修复（本目录 `reader_v5_selfimplemented.py`，
  sha256 `559fd51cb6775502bd7deff95bb779a6d3a75b5ccac8fef3c51be5fd2f0b0e1c`）：
  原末端条目在 realpath(parent)+basename 上下文 lexists 检查、ALLOW_MISSING+词法预扫描
  分类解析错误（非目录/权限/循环/悬空祖先/缺失后 ..）、O_EXCL 临时件所有权（创建成功才
  清理、active 异常采样先于 unlink、add_note 不掩盖原始错误、fdopen 失败先 close(fd)）。
- 阶段三：测试 108→135 项（`test_slice_unit_v5_selfimplemented.py`，
  sha256 `d4c37af5b8353aec2e32f5dbeda06a0ae28db8de9f83dd77f77363e9a9dae17c`）、
  v5 包（`verification_v5/`）、隔离冷读五负例、旧反例翻转，全部基于 559fd51c 字节。
- 阶段四（部分）：受监护全量 run `c3eto_full_20260909_r2` 业务本体完成
  （stdout 末行 `1689 passed, 7 skipped, 23 warnings in 1663.68s`，junit.xml 已生成），
  但 wsl.exe 前台链被外部终止，supervisor 收尾被带走：无 run_record.json、receipts 空、
  alerts 停在 business_started。该 run 目录保留为失败痕迹，不作验收证据。

## 路线切换

收到交接包（README_AGENT.md 声明"本包交付的是实现代码与测试，不是要求你再根据设计重写
一遍"；待替换 reader blob 正是 93d0172b）后，按其要求切回 blob 基线应用其实现：

- `stage2_6_1/runner/r17_c3_engineering_slice.py` 与
  `stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py`
  还原到 24eaa81 的 blob（93d0172b / 11da1eb7），再由 `apply_implementation.py` 应用。
- 本目录两个副本是自实现路线的唯一留档；`verification_v5/`、`counterexamples/`、
  `runs/c3eto_full_20260909*` 均按"不清除失败痕迹"纪律原样保留。
- 后续验收（新 reader 单元测试、14 次 CLI、v6 包与冷读、受监护全量、E05、报告、提交）
  全部以交接包应用后的候选字节为准；自实现路线证据在报告中如实呈现为对照，不作
  交接包路线的验收证据。
