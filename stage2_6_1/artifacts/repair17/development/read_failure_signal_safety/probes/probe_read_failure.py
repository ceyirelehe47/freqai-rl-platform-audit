#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RCF-01 接手快照反例:读取失败后旧有效批次仍被 pump 消费。

用法: probe_read_failure.py <快照仓库根> <工作临时目录>
在固定接手快照(HEAD=4a3c6a8)副本上运行,验证真实
WinSampleReader.read_new + Supervisor._pump_win_lines:

  1) 健康样本:read_new 返回行,new_valid 含有效样本,pump 刷新
     last_win_line_mono(正常基线);
  2) 遥测文件消失(stat OSError):read_new 提前返回——旧实现
     new_valid 保留上一批,pump 仍遍历旧批次刷新 last_win_line_mono
     (失败读取在持续刷新有效性,15/30s 失联判定被掩盖);
  3) 遥测路径变目录(open OSError):同一条提前返回路径;
  4) stale 掩盖演示:连续多轮 pump,旧实现 last_win_line_mono 一路
     前进,stale=mono-last 恒小于节拍,永不达到 15/30s 门槛。

结论输出 JSON(probe_result 字段);退出码 0=反例成立(旧行为
复现),2=未复现(读取失败未被旧批次掩盖),3=脚本自身错误。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
WORK = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(REPO / "stage2_6_1" / "runner"))

from r17_supervision import Supervisor, WinSampleReader  # noqa: E402


def utc_now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def win_line(run_id: str, seq: int) -> dict:
    return {
        "event": "sample", "run_id": run_id, "seq": seq,
        "utc": utc_now_iso(),
        "perf": {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
                 "commit_limit_gb": 83.0, "phys_total_gb": 63.0},
        "vols": [
            {"vol": "F:", "present": True, "free_gb": 100.0,
             "size_gb": 500.0, "serial": "CFA1", "identity_match": True},
            {"vol": "C:", "present": True, "free_gb": 200.0,
             "size_gb": 900.0, "serial": "CCA1", "identity_match": True}],
        "telemetry_out_writable": True}


def make_sup(base: Path) -> Supervisor:
    args = argparse.Namespace(
        run_dir=str(base / "run"), task_kind="fixture",
        argv=["true"], task_cwd=None, max_seconds=0,
        samples_source="", win_sampler_ps1="/nonexistent.ps1",
        win_volumes="C:,F:", expect_artifact=[], obs_ready_deadline=30.0)
    return Supervisor(args)


def main() -> int:
    result: dict = {"probe": "rcf01_read_failure",
                    "repo": str(REPO)}
    try:
        base = WORK / "rcf01"
        if base.exists():
            shutil.rmtree(base)
        base.mkdir(parents=True)
        sup = make_sup(base)
        sup.win_reader = WinSampleReader(
            sup.win_path_guest, run_id=sup.run_id,
            started_iso=sup._started_utc,
            predates_tolerance_s=sup.policy["startup_admission"][
                "source_utc_tolerance_s"])
        wp = sup.win_path_guest

        # ---- 1) 健康基线:两条有效样本 ----
        wp.write_text(
            json.dumps(win_line(sup.run_id, 1)) + "\n" +
            json.dumps(win_line(sup.run_id, 2)) + "\n",
            encoding="utf-8")
        got = sup._pump_win_lines(10.0)
        result["healthy"] = {
            "returned_sample": bool(got),
            "new_valid_len": len(sup.win_reader.new_valid),
            "last_win_line_mono": sup.last_win_line_mono}
        assert got and len(sup.win_reader.new_valid) == 2
        assert sup.last_win_line_mono == 10.0

        # ---- 2) 形态A:文件消失(stat OSError) ----
        wp.unlink()
        got_a = sup._pump_win_lines(20.0)
        stale_batch_a = list(sup.win_reader.new_valid)
        result["form_a_file_gone"] = {
            "read_new_returned_sample": bool(got_a),
            "new_valid_after_failure": len(stale_batch_a),
            "last_win_line_mono": sup.last_win_line_mono,
            "reproduced": bool(stale_batch_a) and
            sup.last_win_line_mono == 20.0}

        # 恢复文件再写一条新样本,把状态推回健康
        wp.write_text(json.dumps(win_line(sup.run_id, 3)) + "\n",
                      encoding="utf-8")
        sup._pump_win_lines(22.0)
        assert sup.last_win_line_mono == 22.0

        # ---- 3) 形态B:路径变目录(open OSError) ----
        wp.unlink()
        wp.mkdir()
        got_b = sup._pump_win_lines(30.0)
        stale_batch_b = list(sup.win_reader.new_valid)
        result["form_b_path_is_dir"] = {
            "read_new_returned_sample": bool(got_b),
            "new_valid_after_failure": len(stale_batch_b),
            "last_win_line_mono": sup.last_win_line_mono,
            "reproduced": bool(stale_batch_b) and
            sup.last_win_line_mono == 30.0}
        wp.rmdir()

        # ---- 4) stale 掩盖演示(形态A 持续) ----
        monos = [sup.last_win_line_mono]
        for m in (40.0, 50.0, 60.0, 70.0, 80.0):
            sup._pump_win_lines(m)
            monos.append(sup.last_win_line_mono)
        # 每轮"判定时刻-最后有效时刻"的最大值:
        max_stale_seen = 0.0
        for judge, last in zip((40.0, 50.0, 60.0, 70.0, 80.0), monos[1:]):
            max_stale_seen = max(max_stale_seen, judge - last)
        result["stale_masking"] = {
            "last_win_line_mono_series": monos,
            "max_stale_s_observed": max_stale_seen,
            "warn_threshold_s": 15.0, "crit_threshold_s": 30.0,
            "reproduced": max_stale_seen < 15.0,
            "note": "旧实现:失败读取每轮刷新有效性,stale 永不达到"
                    "15/30s 门槛(host 失联保护被掩盖)"}

        reproduced = (
            result["form_a_file_gone"]["reproduced"] and
            result["form_b_path_is_dir"]["reproduced"] and
            result["stale_masking"]["reproduced"])
        result["probe_result"] = (
            "REPRODUCED" if reproduced else "NOT_REPRODUCED")
    except AssertionError as exc:
        result["probe_result"] = "SCRIPT_ASSERT_FAIL"
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 3
    except Exception as exc:  # noqa: BLE001 —— 反例脚本如实报自身错误
        result["probe_result"] = "SCRIPT_ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if reproduced else 2


if __name__ == "__main__":
    sys.exit(main())
