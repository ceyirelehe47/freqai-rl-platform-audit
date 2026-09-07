# -*- coding: utf-8 -*-
"""RSS-03 反例:旧"冷读"只复制 manifest/anchor,verify 仍读原根。

上轮交付事实(接手版,只读):
  read_failure_closure/cold_read_final/ 只有 manifest+anchor(+回执),
  无任何 run 字节;其 verify 回执的 --root 指向原始 full_regression。

本 probe 行为复现(不动任何已提交原件):
  1) 按旧脚本同款方式在新位置建 cold copy(只复制 manifest+anchor);
  2) verify 调用 A:--root=<原始 full_regression>(旧交付实际形态)
     ——期望 rc=0,证明"验收通过"依赖原根字节,不是独立副本;
  3) verify 调用 B:--root=<新 cold copy 的 payload 根>(无 run 字节)
     ——期望 rc!=0,证明该副本无法独立核验(缺件不回退原根的对照)。

reproduced = A 过 + cold copy 中 run 文件数为 0。

用法(WSL):
  R17U_SNAP=$HOME/r17u_snap_handover \
  python3 probe_rss03_cold_read.py <输出json路径>
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SNAP = Path(os.environ["R17U_SNAP"])
OUT = Path(sys.argv[1])
RELEASE = Path("/mnt/f/trading/freqai-rl-audit")
OLD = RELEASE / "stage2_6_1/artifacts/repair17/development/read_failure_closure"
ORIG_ROOT = (OLD.parent / "read_failure_signal_safety/full_regression")
MANIFEST = OLD / "delivery_manifest_v2.jsonl"
ANCHOR = OLD / "anchors/final.anchor.json"


def run_verify(root: Path, manifest: Path, anchor: Path,
               receipt_dir: Path, run_record: Path | None):
    cmd = [sys.executable, str(SNAP / "r17_verify_delivery.py"),
           "verify", "--root", str(root),
           "--manifest", str(manifest),
           "--anchor-file", str(anchor),
           "--receipt-dir", str(receipt_dir)]
    if run_record is not None:
        cmd += ["--run-record", str(run_record)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr)[-600:]


def main() -> None:
    cold = OUT.parent / "cold_copy_oldstyle"
    if cold.exists():
        shutil.rmtree(cold)
    cold.mkdir(parents=True)
    # 旧脚本同款:只复制 manifest+anchor(不动原件)
    shutil.copy2(MANIFEST, cold / MANIFEST.name)
    shutil.copy2(ANCHOR, cold / ANCHOR.name)

    run_id = "final_20260907T140907"
    orig_run_dir = ORIG_ROOT / "runs" / run_id
    payload_root = cold / "payload"
    payload_root.mkdir()
    run_files = [p for p in payload_root.rglob("*") if p.is_file()]

    rc_a, tail_a = run_verify(
        ORIG_ROOT, cold / MANIFEST.name, cold / ANCHOR.name,
        OUT.parent / "receipts_rss03_oldstyle", orig_run_dir / "run_record.json")
    rc_b, tail_b = run_verify(
        payload_root, cold / MANIFEST.name, cold / ANCHOR.name,
        OUT.parent / "receipts_rss03_payload", None)
    # B 不传 run-record(新根内无该文件;锚含 run_record_sha256 时
    # verify 自身会要求——这也是"不回退原根"的正当失败形态之一)

    result = {
        "probe": "rss03_cold_read",
        "old_cold_read_files": sorted(
            p.name for p in (OLD / "cold_read_final").iterdir()),
        "cold_copy_run_files": len(run_files),
        "verify_a_root": str(ORIG_ROOT),
        "verify_a_rc": rc_a,
        "verify_a_tail": tail_a[-200:],
        "verify_b_root": str(payload_root),
        "verify_b_rc": rc_b,
        "verify_b_tail": tail_b[-200:],
    }
    # A 通过 = 旧交付形态的验收事实上读取原根;副本零 run 字节
    # = 该"冷读"不独立。B 失败为对照(独立副本缺件应当失败)。
    result["reproduced"] = bool(rc_a == 0 and rc_b != 0
                                and not run_files)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
