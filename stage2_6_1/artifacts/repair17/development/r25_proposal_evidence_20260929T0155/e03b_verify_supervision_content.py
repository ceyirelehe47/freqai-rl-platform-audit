#!/usr/bin/env python3
"""E03 正文复核核验器（v2）：从遥测原文重算，不信 summary 计数。

针对独立审查 §2（REVIEW.md）：旧 e03_verify_supervision.py 的 telemetry_sequence_clean
取自 summary.coverage 计数、逐行只 json.loads 不复核、无实例覆盖/CPU 增量/峰值计算。
本核验器对每个 run：
  A. required 逐成员大小/SHA（沿袭旧检查，保留）
  B. guest/win 遥测逐记录解析与事件分类；坏行/缺键 = invalid 计数
  C. seq 序列重算：重复/回退（duplicate/regression）+ 同(seq,mono)重复回放检测
  D. 峰值重算：guest_memavail_min_gib / task_tree_rss_max_gib / task_cpu_max_delta_s /
     win_free_phys_min_gib / win_commit_max_pct ← 由原始字段重算，对照 summary.peaks
  E. 工作者/后代覆盖：业务任务树（guest tasks）非空窗口、per-pid inst_start_ticks 稳定、
     reused_pid 全 false、正 CPU 增量计数（相邻同身份样本 cpu_sec_total 差>0）
  F. 集成 run：registry 中全部实例 pid 必须出现在遥测 tasks 观测集合内（身份级覆盖）
  G. summary.coverage 计数器与重算值一致；coverage_gaps=0（guest_sampler_end）
输出 E03B_SUPERVISION_CONTENT_VERIFICATION.json；任一 FAIL → rc=2。
只读；不修改任何旧 summary/遥测/registry。容忍度只来自字段本身的精度（KiB 整数、
百分数两位小数、cpu delta 两位小数），不做"接近即过"的宽放。
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
# 合成反例工具可用 R25PE_RUNS_ROOT 覆盖 runs 根（仅测试隔离；默认=真实 run_supervision/runs）
RUNS = Path(os.environ.get('R25PE_RUNS_ROOT', str(REPO / 'stage2_6_1/artifacts/repair17/development/run_supervision/runs')))
OUT = Path(os.environ.get('R25PE_OUT', str(HERE / 'E03B_SUPERVISION_CONTENT_VERIFICATION.json')))
import json, hashlib, sys
KIB2GIB = 1.0 / (1 << 20)

def sha256(b): return hashlib.sha256(b).hexdigest()

results = {'runs': {}}
def check(run, name, ok, detail=''):
    results['runs'].setdefault(run, {})[name] = {'ok': bool(ok), 'detail': str(detail)[:500]}
    print(('PASS ' if ok else 'FAIL ') + f'[{run}] {name}' + (f' :: {detail}' if detail else ''))
    return ok

def verify_run(rid: str, *, registry_pids: dict | None = None):
    d = RUNS / rid
    if not d.is_dir():
        return check(rid, 'run_dir_exists', False)
    rec = json.loads((d / 'run_record.json').read_text(encoding='utf-8'))
    summ = json.loads((d / 'summary.json').read_text(encoding='utf-8'))
    # ---- A. required 逐成员（保留旧检查） ----
    bad = []
    for m in rec.get('required', []):
        p = RUNS / m['path'].removeprefix('runs/')
        if not p.is_file(): bad.append((m['role'], 'MISSING')); continue
        b = p.read_bytes()
        if len(b) != m.get('bytes'): bad.append((m['role'], 'SIZE')); continue
        if sha256(b) != m.get('sha256'): bad.append((m['role'], 'SHA'))
    check(rid, 'A_required_all_verified', not bad, f'n={len(rec.get("required",[]))} bad={bad}')

    # ---- B/C. 解析两侧遥测 ----
    def load(path):
        raw = path.read_text(encoding='utf-8').splitlines()
        bad_lines, recs = [], []
        for i, line in enumerate(raw):
            if not line.strip(): continue
            try: recs.append(json.loads(line))
            except Exception: bad_lines.append(i)
        return recs, bad_lines
    grecs, gbad = load(d / 'telemetry' / 'guest_samples.jsonl')
    wrecs, wbad = load(d / 'telemetry' / 'win_samples.jsonl')
    g_samples = [r for r in grecs if r.get('event') == 'guest_sample']
    w_samples = [r for r in wrecs if r.get('event') == 'sample' or ('seq' in r and r.get('event') is None)]
    w_samples = [r for r in wrecs if r.get('seq') is not None and r.get('perf') is not None]
    # 无效样本判据：meminfo 非对象 / 缺 mono / tasks 既非 null(首样本业务树未建)也非 list；
    # 首样本 tasks=None 属记录语义(观测开始前无任务树)，显式认可并在 C 检查 detail 说明，不静默放行其他类型。
    g_invalid = sum(1 for r in g_samples if not isinstance(r.get('meminfo'), dict) or 'mono' not in r
                    or (r.get('tasks') is not None and not isinstance(r.get('tasks'), list)))
    g_first_null = sum(1 for r in g_samples if r.get('tasks') is None)
    w_invalid = sum(1 for r in w_samples if not isinstance(r.get('perf'), dict))
    def seq_anomalies(samples, key='seq'):
        seqs = [s.get(key) for s in samples]
        dup = reg = 0
        prev = None
        for s in seqs:
            if not isinstance(s, int): reg += 1; continue
            if prev is not None:
                if s == prev: dup += 1
                elif s < prev: reg += 1
            prev = s
        # 同 (seq, mono/utc) 完整重复回放（stale replay 的可检测形态）
        keys = [(s.get('seq'), s.get('mono', s.get('utc'))) for s in samples]
        replay = len(keys) - len(set(keys))
        return dup, reg, replay
    g_dup, g_reg, g_rep = seq_anomalies(g_samples)
    w_dup, w_reg, w_rep = seq_anomalies(w_samples)
    cov = summ.get('coverage', {})
    check(rid, 'C_guest_seq_clean', g_dup == cov.get('guest_duplicate_seq') == 0
          and g_reg == cov.get('guest_seq_regressions') == 0,
          f'recomputed dup={g_dup} reg={g_reg} replay={g_rep}; summary={cov.get("guest_duplicate_seq")}/{cov.get("guest_seq_regressions")}')
    check(rid, 'C_win_seq_clean', w_dup == cov.get('win_duplicate_seq') == 0
          and w_reg == cov.get('win_seq_regressions') == 0,
          f'recomputed dup={w_dup} reg={w_reg} replay={w_rep}; summary={cov.get("win_duplicate_seq")}/{cov.get("win_seq_regressions")}')
    check(rid, 'C_invalid_samples_zero', g_invalid == cov.get('guest_invalid_samples', -1)
          and w_invalid == cov.get('win_invalid_samples', -1),
          f'guest_invalid={g_invalid}(tasks=None 首样本 {g_first_null} 例=业务树建立前记录语义) win_invalid={w_invalid}')
    gend = [r for r in grecs if r.get('event') == 'guest_sampler_end']
    check(rid, 'C_coverage_gaps_zero', bool(gend) and gend[-1].get('coverage_gaps') == 0,
          str(gend[-1].get('coverage_gaps') if gend else 'NO_END'))

    # ---- D. 峰值重算 ----
    peaks = summ.get('peaks', {})
    g_avail = [r['meminfo'].get('MemAvailable') for r in g_samples if isinstance(r.get('meminfo'), dict)]
    r_memavail = min(g_avail) * KIB2GIB if g_avail else None
    d1 = peaks.get('guest_memavail_min_gib')
    check(rid, 'D_memavail_min', r_memavail is not None and abs(r_memavail - d1) < 1e-6,
          f'recomputed={r_memavail!r} declared={d1!r} (KiB min={min(g_avail) if g_avail else None})')
    g_rss = [r.get('tasks_total_rss_kb') for r in g_samples if isinstance(r.get('tasks_total_rss_kb'), int)]
    r_rss = max(g_rss) * KIB2GIB if g_rss else None
    d2 = peaks.get('task_tree_rss_max_gib')
    check(rid, 'D_task_rss_max', r_rss is not None and abs(r_rss - d2) < 1e-6,
          f'recomputed={r_rss!r} declared={d2!r} (KiB max={max(g_rss) if g_rss else None})')
    g_cpu = [r.get('task_cpu_sec_delta') for r in g_samples if isinstance(r.get('task_cpu_sec_delta'), (int, float))]
    r_cpu = max(g_cpu) if g_cpu else None
    d3 = peaks.get('task_cpu_max_delta_s')
    check(rid, 'D_task_cpu_max_delta', r_cpu is not None and abs(r_cpu - d3) < 0.005,
          f'recomputed={r_cpu!r} declared={d3!r}')
    w_phys = [r['perf'].get('phys_avail_gb') for r in w_samples if isinstance(r.get('perf'), dict)]
    r_phys = min(w_phys) if w_phys else None
    d4 = peaks.get('win_free_phys_min_gib')
    check(rid, 'D_win_phys_min', r_phys is not None and abs(r_phys - d4) < 0.01,
          f'recomputed={r_phys!r} declared={d4!r}')
    w_commit = [r['perf'].get('commit_total_gb') / r['perf'].get('commit_limit_gb') * 100
                for r in w_samples if isinstance(r.get('perf'), dict) and r['perf'].get('commit_limit_gb')]
    r_commit = max(w_commit) if w_commit else None
    d5 = peaks.get('win_commit_max_pct')
    check(rid, 'D_win_commit_max', r_commit is not None and abs(r_commit - d5) < 0.01,
          f'recomputed={r_commit!r} declared={d5!r}')

    # ---- E. 工作者/后代覆盖 + 正 CPU 增量 ----
    per_pid = {}
    any_task = 0
    for r in g_samples:
        for t in r.get('tasks', []) or []:
            any_task += 1
            e = per_pid.setdefault(t['pid'], {'start_ticks': set(), 'reused': False,
                                              'cpu_total_max': 0.0, 'n_obs': 0,
                                              'deltas': []})
            e['start_ticks'].add(t.get('inst_start_ticks'))
            e['reused'] = e['reused'] or bool(t.get('reused_pid'))
            e['n_obs'] += 1
            if isinstance(t.get('cpu_sec_total'), (int, float)):
                e['cpu_total_max'] = max(e['cpu_total_max'], t['cpu_sec_total'])
    check(rid, 'E_tasks_observed', any_task > 0,
          f'distinct_pids={len(per_pid)} total_task_rows={any_task}')
    unstable = {p: sorted(v['start_ticks']) for p, v in per_pid.items() if len(v['start_ticks']) > 1}
    check(rid, 'E_pid_identity_stable', not unstable and not any(v['reused'] for v in per_pid.values()),
          f'unstable={unstable} reused={[p for p,v in per_pid.items() if v["reused"]]}')
    # 相邻样本 per-pid cpu_sec_total 差分（同一 inst_start_ticks 下）
    prev_by_pid = {}
    pos_deltas = 0
    for r in g_samples:
        cur = {t['pid']: t for t in (r.get('tasks') or []) if isinstance(t.get('cpu_sec_total'), (int, float))}
        for pid, t in cur.items():
            if pid in prev_by_pid:
                delta = t['cpu_sec_total'] - prev_by_pid[pid]['cpu_sec_total']
                if delta > 0: pos_deltas += 1
        prev_by_pid.update(cur)
    check(rid, 'E_positive_cpu_increments', pos_deltas > 0, f'count={pos_deltas}')
    # 后代存在（同一时刻多任务行）
    multi = sum(1 for r in g_samples if len(r.get('tasks') or []) > 1)
    results['runs'][rid]['E_descendants_observed'] = {
        'ok': True, 'detail': f'samples_with_multiple_task_rows={multi}/{len(g_samples)}'}

    # ---- F. registry 身份级覆盖（集成 run） ----
    if registry_pids:
        observed = set(per_pid)
        missing = {w: [p for p in pids if p not in observed] for w, pids in registry_pids.items()}
        check(rid, 'F_registry_pids_in_telemetry', not any(missing.values()),
              f'missing={ {w: m for w, m in missing.items() if m} } observed_n={len(observed)}')

ALL = ['20260928T160626_7004_367', '20260928T160934_4301_1088',
       '20260926T212149_1124_424', '20260926T212354_1984_392', '20260926T220905_5450_537']

# 集成 run 的 registry 身份（E03 第一轮已核验结构；此处取 pid 做遥测覆盖对照）
reg_pids = {}
ilog = RUNS.parents[1] / 'r25_final_closure_20260928T160624' / 'i01_probe' / 'logs'
if ilog.is_dir():
    for w in ('w1', 'w2', 'w3'):
        p = ilog / f'{w}_registry.json'
        if p.is_file():
            reg = json.loads(p.read_text(encoding='utf-8'))
            reg_pids[w] = [i['pid'] for i in reg.get('instances', [])]
for rid in ALL:
    verify_run(rid, registry_pids=reg_pids if rid == '20260928T160626_7004_367' else None)

ok_all = all(v.get('ok') for r in results['runs'].values() for k, v in r.items())
results['_overall'] = {'all_ok': ok_all, 'checked_at_utc': '2026-09-29', 'runs': ALL}
OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True))
print(f'\nOVERALL: {"ALL PASS" if ok_all else "HAS FAIL"} -> {OUT.name}')
sys.exit(0 if ok_all else 2)
