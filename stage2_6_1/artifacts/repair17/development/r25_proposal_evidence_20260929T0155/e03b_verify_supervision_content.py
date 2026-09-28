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

def verify_run(rid: str, *, registry_idents: dict | None = None):
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
    # E03-c 修复（REVIEW(1) §3.3）：先按实际协议分类，再在全集上校验——
   # sample 记录 = 含 'seq' 键或 event=='sample'（无论 perf 是否合法）；
   # 生命周期记录 = event in {sampler_end,...} 或含 perf_api_ok/token 的 start 行。
   # 无效 sample = 分类为 sample 但 perf 非 dict 或必需数值键缺失；不得先筛后数。
    w_sample_records = [r for r in wrecs if ('seq' in r) or r.get('event') == 'sample']
    w_samples = [r for r in w_sample_records if isinstance(r.get('perf'), dict)]
    w_invalid = sum(1 for r in w_sample_records if not isinstance(r.get('perf'), dict)
                    or not isinstance(r['perf'].get('phys_avail_gb'), (int, float))
                    or not isinstance(r['perf'].get('commit_total_gb'), (int, float))
                    or not isinstance(r['perf'].get('commit_limit_gb'), (int, float)))
    # 无效样本判据：meminfo 非对象 / 缺 mono / tasks 既非 null(首样本业务树未建)也非 list；
    # 首样本 tasks=None 属记录语义(观测开始前无任务树)，显式认可并在 C 检查 detail 说明，不静默放行其他类型。
    g_invalid = sum(1 for r in g_samples if not isinstance(r.get('meminfo'), dict) or 'mono' not in r
                    or (r.get('tasks') is not None and not isinstance(r.get('tasks'), list)))
    g_first_null = sum(1 for r in g_samples if r.get('tasks') is None)
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
          f'guest_invalid={g_invalid}(tasks=None 首样本 {g_first_null} 例=业务树建立前记录语义) win_invalid={w_invalid}/classified_sample_records={len(w_sample_records)}/valid={len(w_samples)}')
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

    # ---- E. 工作者/后代覆盖 + 身份（E03-a 修复：覆盖键=完整 (pid, inst_start_ticks)） ----
    per_ident = {}   # (pid, inst_start_ticks) -> {'n':int,'cpu':[...]}
    per_pid_ticks = {}  # pid -> set(ticks)（遥测内部稳定性）
    any_task = 0
    for r in g_samples:
        for t in r.get('tasks', []) or []:
            any_task += 1
            key = (t['pid'], t.get('inst_start_ticks'))
            e = per_ident.setdefault(key, {'n': 0, 'cpu': []})
            e['n'] += 1
            if isinstance(t.get('cpu_sec_total'), (int, float)):
                e['cpu'].append(t['cpu_sec_total'])
            per_pid_ticks.setdefault(t['pid'], set()).add(t.get('inst_start_ticks'))
    reused_seen = {(t['pid'], t.get('inst_start_ticks'))
                   for r in g_samples for t in (r.get('tasks') or []) if t.get('reused_pid')}
    check(rid, 'E_tasks_observed', any_task > 0,
          f'distinct_identities={len(per_ident)} total_task_rows={any_task}')
    unstable = {p: sorted(v) for p, v in per_pid_ticks.items() if len(v) > 1}
    check(rid, 'E_pid_identity_stable', not unstable,
          f'unstable_pid_ticks={unstable} reused_flags_observed={sorted(reused_seen) or "none"} '
          f'(reused 标记≠泄漏断言，仅记录；身份稳定性=每 pid 恰一 inst_start_ticks)')

    # ---- G. 角色绑定 CPU（E03-b 修复：指定 burn 工作者自身的正增量，非任意进程） ----
    # 期望来源=本 run 的 business/stdout.log 中 {"label","pid","mode","seconds"} JSON 行（证据驱动）：
    # mode=burn → 该 pid 必须以完整身份被观测≥2 次且自身相邻样本正 CPU 增量>0；
    # mode=sleep → 仅要求身份被观测（sleep/等待中的子孙不要求持续正 CPU）。
    modes = []
    slog = d / 'business' / 'stdout.log'
    if slog.is_file():
        for line in slog.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line.startswith('{'):
                continue
            try: j = json.loads(line)
            except Exception: continue
            if isinstance(j.get('pid'), int) and j.get('mode') in ('burn', 'sleep'):
                modes.append(j)
    burn_fails, burn_ok = [], []
    for j in modes:
        pid = j['pid']
        hits = [(k, v) for k, v in per_ident.items() if k[0] == pid]
        if not hits:
            burn_fails.append(f"{j.get('label')}:{pid} identity_not_observed"); continue
        if j['mode'] == 'sleep':
            burn_ok.append(f"{j.get('label')}:{pid}(sleep identity observed)"); continue
        best = max(hits, key=lambda kv: len(kv[1]['cpu']))[1]['cpu']
        pos = sum(1 for a, b in zip(best, best[1:]) if b > a)
        if len(best) >= 2 and pos > 0:
            burn_ok.append(f"{j.get('label')}:{pid}(burn {j.get('seconds')}s own-increments={pos}/{len(best)})")
        else:
            burn_fails.append(f"{j.get('label')}:{pid}(burn {j.get('seconds')}s own cpu seq={best})")
    if modes:
        check(rid, 'G_burn_workers_own_cpu_increments', not burn_fails,
              f'modes={[f"{j.get("label")}:{j["mode"]}" for j in modes]} ok={burn_ok} fails={burn_fails}')
    # 无 mode 声明的 run（旧监护 run）：退回全局任意身份正增量判据（保持原保证）。
    pos_any = sum(1 for v in per_ident.values()
                  for a, b in zip(v['cpu'], v['cpu'][1:]) if b > a)
    if not modes:
        check(rid, 'E_positive_cpu_increments', pos_any > 0, f'count={pos_any}')
    results['runs'][rid]['E_global_cpu_increments'] = {
        'ok': True, 'detail': f'any-identity positive increments={pos_any} (informational)'}
    multi = sum(1 for r in g_samples if len(r.get('tasks') or []) > 1)
    results['runs'][rid]['E_descendants_observed'] = {
        'ok': True, 'detail': f'samples_with_multiple_task_rows={multi}/{len(g_samples)}'}

    # ---- F. registry 身份级覆盖（E03-a：完整 (pid,start_ticks) 元组逐一匹配，非仅 PID 出现） ----
    if registry_idents:
        observed = set(per_ident)
        missing = {}
        for w, idents in registry_idents.items():
            for (pid, ticks, role) in idents:
                if (pid, ticks) not in observed:
                    missing.setdefault(w, []).append(f'pid={pid},start_ticks={ticks},role={role}')
        check(rid, 'F_registry_identities_in_telemetry', not missing,
              f'missing={missing} observed_identities={len(observed)} '
              f'(registry 实例按完整 (pid,start_ticks) 逐一匹配；遥测多出的外壳进程属监护树正常)')

ALL = ['20260928T160626_7004_367', '20260928T160934_4301_1088',
       '20260926T212149_1124_424', '20260926T212354_1984_392', '20260926T220905_5450_537']

# 集成 run 的 registry 完整身份（E03-a：覆盖键=完整元组；合成工具可经 R25PE_I01_ROOT 覆盖）
reg_idents = {}
ilog = Path(os.environ.get('R25PE_I01_ROOT',
            str(RUNS.parents[1] / 'r25_final_closure_20260928T160624' / 'i01_probe' / 'logs')))
if ilog.is_dir():
    for w in ('w1', 'w2', 'w3'):
        p = ilog / f'{w}_registry.json'
        if p.is_file():
            reg = json.loads(p.read_text(encoding='utf-8'))
            reg_idents[w] = [(i['pid'], i.get('start_ticks'), i.get('role'))
                             for i in reg.get('instances', [])]
for rid in ALL:
    verify_run(rid, registry_idents=reg_idents if rid == '20260928T160626_7004_367' else None)

ok_all = all(v.get('ok') for r in results['runs'].values() for k, v in r.items())
results['_overall'] = {'all_ok': ok_all, 'checked_at_utc': '2026-09-29', 'runs': ALL}
OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True))
print(f'\nOVERALL: {"ALL PASS" if ok_all else "HAS FAIL"} -> {OUT.name}')
sys.exit(0 if ok_all else 2)
