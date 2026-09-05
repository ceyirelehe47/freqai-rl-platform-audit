"""F3 反例探针(隔离版):R16 权威 journal 拒绝污染 + 无串行 seq +
parser 缺迁移校验。

每个场景独立 state root + 独立子进程,互不污染。真实模块
curriculum261_r16_execgov@d2ee974;零正式数据。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJ = Path.home() / "projects" / "crypto_rl"
LIB = str(PROJ / "src")

SCEN_C1 = r'''
import json, sys
sys.path.insert(0, {lib!r})
import os
os.environ["CURRICULUM261_R16_STATE_ROOT"] = {root!r}
from rl_curriculum.curriculum261_r16_execgov import (
    R16FormalSession, R16OwnershipError, journal_entries)
s = R16FormalSession.acquire({{"probe": "c1-owner"}})
before = len(journal_entries())
try:
    R16FormalSession.acquire({{"probe": "c1-loser"}})
except R16OwnershipError:
    pass
after = journal_entries()
rej = [e for e in after if e["event"] == "session_rejected"]
print(json.dumps({{"n_before": before, "n_after": len(after),
                   "n_session_rejected": len(rej),
                   "rejected_events": rej}}))
s.release(summary="c1 cleanup")
'''

SCEN_C2 = r'''
import json, sys
sys.path.insert(0, {lib!r})
import os
os.environ["CURRICULUM261_R16_STATE_ROOT"] = {root!r}
import multiprocessing as mp
from rl_curriculum.curriculum261_r16_execgov import (
    journal_append, r16_journal_path)

def worker(b):
    b.wait()
    journal_append("session_rejected", {{"reason": "concurrent-probe"}},
                   durable=False)

if __name__ == "__main__":
    b = mp.Barrier(6)
    ps = [mp.Process(target=worker, args=(b,)) for _ in range(6)]
    [p.start() for p in ps]
    [p.join() for p in ps]
    # 直接读原始行统计 seq(journal_entries 会把重复 seq 行判 corrupt 丢弃)
    raw = [json.loads(l) for l in
           open(r16_journal_path(), encoding="utf-8") if l.strip()]
    seqs = [r.get("seq") for r in raw]
    print(json.dumps({{"seqs": seqs, "n_lines": len(raw),
                       "duplicate_seq_present": len(seqs) != len(set(seqs))}}))
'''

SCEN_C3A = r'''
import json, sys
sys.path.insert(0, {lib!r})
import os
os.environ["CURRICULUM261_R16_STATE_ROOT"] = {root!r}
from rl_curriculum.curriculum261_r16_execgov import (
    journal_append, journal_entries, R16JournalCorruption)
# 无 session_acquired / 无 exposure 的孤立 grant_issued(合法 JSON)
journal_append("grant_issued", {{"session": "0" * 64, "grant": "1" * 64,
                                 "namespaces": ["probe_ns"]}})
try:
    es = journal_entries()
    print(json.dumps({{"accepted": True, "n_entries": len(es)}}))
except R16JournalCorruption as e:
    print(json.dumps({{"accepted": False, "error": str(e)[:150]}}))
'''

SCEN_C3B = r'''
import json, sys
sys.path.insert(0, {lib!r})
import os
os.environ["CURRICULUM261_R16_STATE_ROOT"] = {root!r}
from rl_curriculum.curriculum261_r16_execgov import (
    journal_append, journal_entries, R16JournalCorruption)
# exposure 之前的 qualification_terminal(合法 JSON;状态矛盾)
journal_append("qualification_terminal", {{"session": "2" * 64,
    "status": "completed", "plan_digest": "x"}})
try:
    es = journal_entries()
    print(json.dumps({{"accepted": True, "n_entries": len(es)}}))
except R16JournalCorruption as e:
    print(json.dumps({{"accepted": False, "error": str(e)[:150]}}))
'''

SCEN_C4 = r'''
import json, sys
sys.path.insert(0, {lib!r})
import os
os.environ["CURRICULUM261_R16_STATE_ROOT"] = {root!r}
from rl_curriculum.curriculum261_r16_execgov import (
    journal_entries, R16JournalCorruption, r16_journal_path)
path = r16_journal_path()
path.parent.mkdir(parents=True, exist_ok=True)
rec = {{"seq": 1, "utc": "2026-01-01T00:00:00+00:00",
        "event": "session_acquired", "iteration": "r16", "pid": 1,
        "session": "a" * 64, "binding": {{}}}}
with open(path, "w", encoding="utf-8") as fh:
    fh.write(json.dumps(rec, sort_keys=True) + "\n")
    fh.write(json.dumps(rec, sort_keys=True) + "\n")  # 重复 seq=1
try:
    journal_entries()
    print(json.dumps({{"corruption_raised": False}}))
except R16JournalCorruption as e:
    print(json.dumps({{"corruption_raised": True, "error": str(e)[:150]}}))
'''


def run(name: str, template: str) -> dict:
    root = tempfile.mkdtemp(prefix=f"r17_f3_{name}_")
    code = template.format(lib=LIB, root=root)
    with tempfile.NamedTemporaryFile("w", suffix=f"_{name}.py",
                                     delete=False,
                                     encoding="utf-8") as fh:
        fh.write(code)
        script = fh.name
    p = subprocess.run([sys.executable, script], capture_output=True,
                       text=True, timeout=180)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        out = {"parse_error": p.stdout[-300:], "stderr": p.stderr[-300:]}
    out["_returncode"] = p.returncode
    out["_state_root"] = root
    return out


def main() -> None:
    results: dict[str, object] = {}
    c1 = run("c1", SCEN_C1)
    results["C1_rejected_written_to_authoritative_journal"] = {
        **c1,
        "defect": c1.get("n_session_rejected", 0) >= 1
        and "抢锁失败的竞争请求写入了权威 journal",
    }
    c2_runs = [run("c2", SCEN_C2) for _ in range(5)]
    results["C2_concurrent_append_duplicate_seq"] = {
        "runs": c2_runs,
        "any_duplicate": any(r.get("duplicate_seq_present")
                             for r in c2_runs),
        "note": "journal_append 的 seq=无锁 lenient+1;并发竞争者可写"
                "重复/交错行;即使未撞上,拒绝写权威 journal 已是 C1",
    }
    c3a = run("c3a", SCEN_C3A)
    results["C3a_parser_accepts_orphan_grant"] = {
        **c3a,
        "defect": c3a.get("accepted") is True
        and "strict parser 未拒绝无 session 前置的 grant_issued",
    }
    c3b = run("c3b", SCEN_C3B)
    results["C3b_parser_accepts_terminal_before_exposure"] = {
        **c3b,
        "defect": c3b.get("accepted") is True
        and "strict parser 未拒绝 exposure 前的 qualification_terminal",
    }
    c4 = run("c4", SCEN_C4)
    results["C4_duplicate_seq_blocks_owner"] = {
        **c4,
        "defect": c4.get("corruption_raised") is True
        and "重复 seq 令正常 owner 的下一次授权判定 fail closed",
    }

    out_path = Path("/mnt/e/trading/freqai-rl-audit/stage2_6_1/"
                    "artifacts/repair17/development/f1_f5_reproduction/"
                    "f3_journal_pollution_counterexample.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"format": "r17-f3-counterexample-v1",
               "module_under_test":
                   "rl_curriculum.curriculum261_r16_execgov@d2ee974",
               "results": results},
              open(out_path, "w"), indent=1, ensure_ascii=False)
    summary = {}
    for k, v in results.items():
        if isinstance(v, dict):
            summary[k] = v.get("defect", v.get("any_duplicate"))
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    print("written:", out_path)


if __name__ == "__main__":
    main()
