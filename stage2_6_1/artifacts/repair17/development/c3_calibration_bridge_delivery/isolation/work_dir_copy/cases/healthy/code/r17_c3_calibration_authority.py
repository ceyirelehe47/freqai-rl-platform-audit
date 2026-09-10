"""Thin, generation-free consumer of the repository's R4 statistics / R5 gate.
Imports may load project modules; no generator, evaluator, scaler or trainer is called.
"""
from __future__ import annotations
import importlib
import math
from pathlib import Path
import sys
from r17_c3_calibration_bridge import (CONTRACT, SPLITS, RUNGS, POLICIES, BASELINES,
                                     KAPPA, BOOTSTRAP_N, BOOTSTRAP_SEED, need, meta,
                                     sign_counts, validate_rows, NOT_EVALUATED)
import r17_c3_reserve_batch as batch


def ensure_imports():
    try:
        import rl_curriculum.curriculum261_api
    except ModuleNotFoundError as exc:
        if exc.name not in ('rl_curriculum','rl_curriculum.curriculum261_api'): raise
        src=Path(__file__).resolve().parent.parent/'src'
        if not src.is_dir(): raise
        sys.path.insert(0,str(src))


class RepositoryAuthority:
    def __init__(self):
        ensure_imports()
        from rl_curriculum import curriculum261_r4_pairs as r4
        from rl_curriculum import curriculum261_r5_pairs as r5
        self.r4,self.r5=r4,r5
        need(r5.ROBUSTNESS_KAPPA_R5==KAPPA,'R5 kappa drift')
        need(r4.R4_BOOTSTRAP_RESAMPLES==BOOTSTRAP_N and r4.R4_BOOTSTRAP_SEED==BOOTSTRAP_SEED,'R4 bootstrap drift')
        need(tuple(r4.REQUIRED_BASELINES[batch.FAMILY])==BASELINES,'baseline contract drift')
        self.describe()

    def describe(self):
        from r17_c3_calibration_source_lock import SOURCE_SHA256
        actual={}
        for name,h in SOURCE_SHA256.items():
            mod=importlib.import_module(name)
            actual[name]=meta(Path(mod.__file__).resolve(strict=True))['sha256']
            need(actual[name]==h,'imported source drift: '+name)
        return {'kind':'repository_r4_r5_primitives','sources':actual}

    def analyze(self,rows):
        validate_rows(rows)
        r4,r5=self.r4,self.r5
        corpora={}
        for split in SPLITS:
            ns=batch.NAMESPACES[split]
            # Caller has already removed pair/trade metadata from numeric returns.
            table=r4.build_pair_evidence_table(rows[split],batch.FAMILY,ns)
            ladder={}
            margins={p:{} for p in BASELINES}
            for rung in RUNGS:
                values=r4.difficulty_series(table,rung)
                ladder[rung]={**r4.cluster_stats(values), 'bootstrap_ci':r4.bootstrap_mean_ci(values)}
                for p in BASELINES:
                    v=r4.margin_series(table,rung,p)
                    margins[p][rung]={**r4.cluster_stats(v),'bootstrap_ci':r4.bootstrap_mean_ci(v)}
            gaps={}
            for a,b in zip(RUNGS,RUNGS[1:]):
                gap=ladder[a]['mean']-ladder[b]['mean']
                se=math.sqrt(ladder[a]['se']**2+ladder[b]['se']**2)
                gaps[a+'-'+b]={'gap':float(gap),'se_pair_cluster':se,
                              'gap_over_se':float(gap/se) if se>0 else None}
            report={'family':batch.FAMILY,'corpus':ns,'pair_table':table,
                    'difficulty_ladder':ladder,'fixed_baseline_margins':margins,
                    'adjacent_rung_gaps':gaps,'pair_integrity_pass_rate':1.0,
                    'oracle_positive_all_rungs':bool(all(r4.table_series(table,r,'oracle').mean()>0 for r in RUNGS))}
            corpora[split]={'report':report,'conditions':r5.corpus_conditions_r5(report,kappa=KAPPA)}
        return {'contract':CONTRACT,'mode':'raw_saved_results','kappa':KAPPA,'corpora':corpora,
                'strict_both_pass':all(corpora[s]['conditions']['pass'] for s in SPLITS),
                'return_counts':sign_counts(rows),
                'not_evaluated':list(NOT_EVALUATED)}
