#!/usr/bin/env python3
"""E03B 合成反例工具：证明正文核验器确实从原文重算（REVIEW §2.3 的等价复现）。

对每个用例构建明确标注 SYNTHETIC_ONLY 的 runs 根（内容变异后**重算 required SHA**，
隔离"内容复核"与"checksum 复核"），用未修改的 e03b_verify_supervision_content.py
（经 R25PE_RUNS_ROOT/R25PE_OUT 注入根）逐例运行并记录 rc 与被触发的 FAIL 检查名。

用例：
  control            内容一致的健康夹具（全部 5 个 run 目录名齐全）        → 期望 rc=0
  seq_anomaly        win seq 改为 1,1,0 且 summary 计数仍为 0                → 期望 rc=2 + C_win_seq_clean FAIL
  empty_coverage     tasks 全空/零 CPU，summary 计数保留                     → 期望 rc=2 + E_* FAIL
  false_peaks        summary 峰值改 9999 与正文不符                          → 期望 rc=2 + D_* FAIL
  sha_tamper         遥测字节改但 required SHA 不更新（负对照=防线确认）     → 期望 rc=2 + A_required FAIL
不触碰任何真实历史材料；产物全部在 synthetic_cases/ 下。
"""
import json, hashlib, subprocess, sys, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERIFIER = HERE / 'e03b_verify_supervision_content.py'
CASES = HERE / 'synthetic_cases'
RUN_NAMES = ['20260928T160626_7004_367', '20260928T160934_4301_1088',
             '20260926T212149_1124_424', '20260926T212354_1984_392',
             '20260926T220905_5450_537']
POLICY_SHA = 'a' * 64

def sha(b): return hashlib.sha256(b).hexdigest()
def jbytes(o): return json.dumps(o, ensure_ascii=False).encode()

def guest_line(event=None, seq=None, mono=None, avail=40_000_000, tasks=None,
               rss=None, cpu_delta=None, utc='2026-09-29T00:00:00Z'):
    if event == 'guest_sampler_start':
        return {'event': event, 'utc': utc, 'pid': 1, 'interval_s': 5.0,
                'pgids': [], 'page_size': 4096, 'clk_tck': 100}
    if event == 'guest_sampler_end':
        return {'event': event, 'utc': utc, 'coverage_gaps': 0}
    return {'event': 'guest_sample', 'utc': utc, 'mono': mono, 'seq': seq,
            'meminfo': {'MemAvailable': avail},
            'run_id': 'x',
            'tasks': tasks,
            'tasks_total_rss_kb': rss,
            'task_count': len(tasks or []),
            'task_cpu_sec_delta': cpu_delta}

def win_line(kind=None, seq=None, phys=40.0, commit=30.0, utc='2026-09-29T00:00:00Z'):
    if kind == 'start':
        return {'pid': 2, 'run_id': 'x', 'interval_s': 5, 'utc': utc,
                'max_seconds': 600, 'token': 'b' * 64, 'n_disks': 4,
                'perf_api_ok': True}
    if kind == 'end':
        return {'event': 'sampler_end', 'pid': 2, 'reason': 'stop_requested',
                'token': 'b' * 64, 'utc': utc, 'run_id': 'x'}
    return {'perf': {'commit_limit_gb': 83.192, 'commit_total_gb': commit,
                     'phys_avail_gb': phys}, 'utc': utc, 'seq': seq,
            'event': 'sample', 'run_id': 'x'}

def task(pid, ticks, cpu_total):
    return {'pid': pid, 'ppid': 1, 'pgrp': 1, 'state': 'S', 'comm': 'python',
            'inst_start_ticks': ticks, 'reused_pid': False, 'rss_kb': 1000,
            'threads': 1, 'cpu_sec_total': cpu_total}

def build_run(root: Path, rid: str, *, n=6, win_seqs=None, tasks_fn=None,
              peaks_override=None, tamper_telemetry=False):
    d = root / 'runs' / rid
    (d / 'telemetry').mkdir(parents=True)
    (d / 'alerts').mkdir(parents=True)
    (d / 'business').mkdir(parents=True)
    (d / 'native_sampler').mkdir(parents=True)
    g = [guest_line('guest_sampler_start')]
    w = [win_line('start')]
    for i in range(n):
        tasks = tasks_fn(i) if tasks_fn else [task(10, 100, 0.5 + i * 0.1)]
        g.append(guest_line(seq=i + 1, mono=i * 5.0, avail=40_000_000 - i * 1000,
                            tasks=tasks, rss=10_000 + i * 100,
                            cpu_delta=0.1))
        w.append(win_line(seq=win_seqs[i] if win_seqs else i + 1,
                          phys=40.0 - i * 0.1, commit=30.0 + i * 0.5))
    g.append(guest_line('guest_sampler_end'))
    w.append(win_line('end'))
    w_clean_bytes = ('\n'.join(json.dumps(r) for r in w) + '\n').encode()
    if tamper_telemetry:
        w[1]['perf']['phys_avail_gb'] = 12.34  # 变异；required 保留变异前 SHA（防线负对照）
    (d / 'telemetry' / 'guest_samples.jsonl').write_text(
        '\n'.join(json.dumps(r) for r in g) + '\n', encoding='utf-8')
    (d / 'telemetry' / 'win_samples.jsonl').write_text(
        '\n'.join(json.dumps(r) for r in w) + '\n', encoding='utf-8')
    (d / 'alerts' / 'alerts.jsonl').write_text('', encoding='utf-8')
    (d / 'business' / 'stdout.log').write_text('SYNTHETIC_ONLY stdout\n', encoding='utf-8')
    (d / 'business' / 'stderr.log').write_text('', encoding='utf-8')
    for name in ('identity.json', 'terminal.json', 'confirmation.json'):
        (d / 'native_sampler' / name).write_text(json.dumps({'synthetic': True}), encoding='utf-8')
    avail_gib = min(40_000_000 - (n - 1) * 1000) if False else (40_000_000 - (n - 1) * 1000) / (1 << 20)
    rss_gib = (10_000 + (n - 1) * 100) / (1 << 20)
    phys_min = 40.0 - (n - 1) * 0.1
    commit_max = (30.0 + (n - 1) * 0.5) / 83.192 * 100
    peaks = {'guest_memavail_min_gib': avail_gib, 'task_tree_rss_max_gib': rss_gib,
             'task_cpu_max_delta_s': 0.1, 'win_free_phys_min_gib': phys_min,
             'win_commit_max_pct': round(commit_max, 2)}
    if peaks_override: peaks.update(peaks_override)
    summary = {'schema': 'r17-supervision-summary-v1', 'run_id': rid,
               'policy_id': 'S', 'policy_sha256': POLICY_SHA,
               'argv': ['synthetic'], 'business': {'rc': 0},
               'incidents': [],
               'coverage': {'win_parse_errors': 0, 'win_invalid_samples': 0,
                            'win_duplicate_seq': 0, 'win_seq_regressions': 0,
                            'guest_duplicate_seq': 0, 'guest_seq_regressions': 0,
                            'guest_invalid_samples': 0},
               'peaks': peaks}
    (d / 'summary.json').write_bytes(jbytes(summary))
    # required：九角色 + 重算 SHA（tamper 用例故意用变异前字节的 SHA）
    files = {
        'telemetry_guest': (d / 'telemetry' / 'guest_samples.jsonl'),
        'telemetry_win': (d / 'telemetry' / 'win_samples.jsonl'),
        'alerts': (d / 'alerts' / 'alerts.jsonl'),
        'business_stdout': (d / 'business' / 'stdout.log'),
        'business_stderr': (d / 'business' / 'stderr.log'),
        'native_sampler_identity': (d / 'native_sampler' / 'identity.json'),
        'native_sampler_terminal': (d / 'native_sampler' / 'terminal.json'),
        'native_sampler_confirmation': (d / 'native_sampler' / 'confirmation.json'),
        'summary': (d / 'summary.json'),
    }
    required = []
    for role, p in files.items():
        b = w_clean_bytes if (tamper_telemetry and role == 'telemetry_win') else p.read_bytes()
        required.append({'role': role,
                         'path': f'runs/{rid}/{p.relative_to(d).as_posix()}',
                         'status': 'present', 'sha256': sha(b),
                         'bytes': len(b)})
    record = {'schema': 'r17-run-record-v2', 'run_id': rid,
              'task_kind': 'engineering', 'argv': ['synthetic'],
              'business': {'rc': 0, 'signal': None},
              'policy': {'id': 'S', 'sha256': POLICY_SHA},
              'required': required, 'evidence_complete': True,
              'missing_roles': [], 'control_failures': [],
              'cutoff_certified': True, 'writers': {}, 'io': {},
              'finalized': True}
    (d / 'run_record.json').write_bytes(jbytes(record))

def build_case(name, **kw):
    root = CASES / name
    if root.exists(): shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / 'SYNTHETIC_ONLY.md').write_text(
        '# SYNTHETIC_ONLY\n本目录全部内容为 E03B 合成反例夹具（REVIEW §2.3 复现），'
        '非真实监护记录；仅用于证明核验器从原文重算。\n', encoding='utf-8')
    for rid in RUN_NAMES:
        build_run(root, rid, **kw)
    return root

def run_case(name, root, expect_rc, expect_fail_substrings):
    out_json = CASES / name / 'verification_result.json'
    env_extra = {'R25PE_RUNS_ROOT': str(root / 'runs'), 'R25PE_OUT': str(out_json)}
    import os
    env = dict(os.environ); env.update(env_extra)
    p = subprocess.run([sys.executable, str(VERIFIER)], capture_output=True,
                       text=True, env=env, cwd=str(HERE))
    fails = [l for l in p.stdout.splitlines() if l.startswith('FAIL ')]
    hit = all(any(s in l for l in fails) for s in expect_fail_substrings)
    ok = (p.returncode == expect_rc) and (expect_rc != 0 or not fails) and hit
    (CASES / name / 'run_log.txt').write_text(
        f'argv: {sys.executable} {VERIFIER}\nenv: R25PE_RUNS_ROOT={root}\n'
        f'rc: {p.returncode} (expect {expect_rc})\n--- stdout ---\n{p.stdout}\n--- stderr ---\n{p.stderr}\n',
        encoding='utf-8')
    print(f"{'PASS' if ok else 'FAIL'} case={name} rc={p.returncode}(exp {expect_rc}) "
          f"fail_lines={[l.split(']')[-1].strip() for l in fails][:4]}")
    return {'case': name, 'rc': p.returncode, 'expect_rc': expect_rc,
            'fails': [l.strip() for l in fails], 'ok': ok}

if CASES.exists(): shutil.rmtree(CASES)
CASES.mkdir(parents=True)
results = []
results.append(run_case('control', build_case('control'), 0, []))
results.append(run_case('seq_anomaly',
    build_case('seq_anomaly', win_seqs=[1, 1, 0, 4, 5, 6]), 2,
    ['C_win_seq_clean']))
results.append(run_case('empty_coverage',
    build_case('empty_coverage', tasks_fn=lambda i: []), 2,
    ['E_tasks_observed', 'E_positive_cpu_increments']))
results.append(run_case('false_peaks',
    build_case('false_peaks', peaks_override={
        'task_tree_rss_max_gib': 9999.0, 'task_cpu_max_delta_s': 9999.0}), 2,
    ['D_task_rss_max', 'D_task_cpu_max_delta']))
results.append(run_case('sha_tamper',
    build_case('sha_tamper', tamper_telemetry=True), 2,
    ['A_required_all_verified']))
all_ok = all(r['ok'] for r in results)
(HERE / 'E03B_SYNTH_COUNTEREXAMPLES.json').write_text(
    json.dumps({'cases': results, 'all_ok': all_ok,
                'note': 'SYNTHETIC_ONLY fixtures; content mutations carry recomputed required SHA (except sha_tamper negative control) to isolate content-level recompute from checksum checks.'},
               indent=1, ensure_ascii=False))
print('\nOVERALL:', 'ALL PASS' if all_ok else 'HAS FAIL')
sys.exit(0 if all_ok else 2)
