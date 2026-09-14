"""Synthetic REPORT fixtures. No episodes, generators, audit MC or V2 fitting.

Native report-shaped scalar/table specimens are intentionally fabricated inputs
for an engineering consumer test. They are never production data or evidence
that a generator / semantic bootstrap / global-K audit has executed.
"""
from __future__ import annotations
import copy
import math
from rl_curriculum import curriculum261_r17_c2_consumer as c


def density():
    from rl_curriculum.curriculum261_r5_pairs import density_gate_r5
    return {r: density_gate_r5({'median_reference_trades_per_episode': 12.,
                               'reference_long_label_rate': .03}) for r in c.RUNGS}


def structure():
    return {'local_cue_independence': {'pass': True},
            'context_observability': {'pass': True},
            'r6_point_separation_diagnostic_only': {'pass': False}}


def block_table(namespace, n=40, *, reverse=False):
    rows = []
    for i in range(n):
        pair_metrics = {}
        for ri, rung in enumerate(c.RUNGS):
            base = (.14, .11, .075, .04)[ri]
            if reverse and rung == 'D2':
                base = .13
            ref = base + .003 * math.sin(i * .73) + .0003 * (ri + 1) * math.cos(i * .37)
            returns = {'reference': ref, 'always_flat': 0., 'always_long': -.001,
                       'c2_local_only': -.002, 'oracle': ref + .03,
                       'reference_trades': 12.}
            pair_metrics[rung] = {'returns': returns, 'difficulty': ref,
                'margins': {b: ref - returns[b] for b in c.BASELINES}}
        rows.append({'corpus': namespace, 'family': 'c2_context', 'block_index': i,
            'shared_tape_digest': f'fixture-tape-{namespace}-{i}', 'selected_attempt': 0,
            'cross_rung_integrity_pass': True, 'pair_integrity_all_pass': True,
            'pair_metrics': pair_metrics,
            'gaps': {hi+'-'+lo: pair_metrics[hi]['difficulty'] - pair_metrics[lo]['difficulty']
                     for hi,lo in zip(c.RUNGS[:-1], c.RUNGS[1:])}})
    return {'corpus': namespace, 'family':'c2_context', 'n_blocks':n, 'rows':rows}


def semantic(cid, phase, split, *, payoff=.01):
    ns=f'fixture_c2_{phase}_{split}_semantic_{cid}'
    sides={s: {'cue_precision': {'bound': .95, 'min': .85, 'pass':True},
               'payoff_false_cue': {'bound': payoff, 'max': .06, 'pass':payoff<=.06},
               'pass': payoff<=.06} for s in ('A','B')}
    candidate={'format':'cur261-r17-candidate-cue-semantics-v1',
               'candidate':cid, 'cluster_unit':'matched_block',
               'per_rung':{r:{'sides':copy.deepcopy(sides),'pass':payoff<=.06} for r in c.RUNGS},
               'pass':payoff<=.06}
    shared={'format':'cur261-r17-semantic-cue-gate-v1',
            'canonical':'D0/A','cluster_unit':'matched_block','n_blocks':160,
            'recall_floor':(.95-.02),'n_unique_positive_cues':4000,'min_unique_positive_cues':3600,
            'recall':{'bound':.96},'noncue_false_positive':{'bound':.001},
            'checks':{k:True for k in c.SHARED_LEAVES},'pass':True}
    native={'format':'cur261-r17-semantic-corpus-v1','namespace':ns,'ladder':cid,
            'n_blocks':160,'semantic_blocks_per_corpus_expected':160,'n_semantic_episodes':1280,
            'shared':shared,'candidate':candidate,'pass':payoff<=.06}
    return c.wrap_report('semantic',phase,split,cid,ns,native)


def independent(cid, phase, split):
    ns=f'fixture_c2_{phase}_{split}_independent_{cid}'
    blocks=block_table(ns,20)
    rows=[{'corpus':ns,'family':'c2_context','rung':r,'pair_index':i,
           'episode_hashes':{s:f'ce-fixture-{ns}-{r}-{i}-{s}' for s in ('A','B')},
           'returns':copy.deepcopy(b['pair_metrics'][r]['returns'])}
          for i,b in enumerate(blocks['rows']) for r in c.RUNGS]
    report={'pair_table':{'corpus':ns,'family':'c2_context','n_pairs':80,'rows':rows},
            'pair_integrity_pass_rate':1.0}
    # The consumer recomputes the statistical summaries from the pair table.
    cond={'namespace':ns,'pairs_per_rung':20,'density_gates':density(),
          'semantics':structure(),
          'cue_semantics':{'structural':{'checks':{'canonical_consistency':True},'pass':True},
                           'cue_point_diagnostics':{'pass':False,'diagnostic_only':True}}}
    return c.wrap_report('independent',phase,split,cid,ns,{'report':report,'conditions':cond})


def make_packet(*, reverse_design=False):
    audit={'format':'cur261-r17-cue-contract-audit-v1','audit_blocks_per_corpus':500,
           'audit_namespaces':{'model':'fixture_c2_audit_model','validation':'fixture_c2_audit_validation'},
           'formal_audit':False,'p_contract':.95,
           'noninferiority':{'recall_floor':(.95-.02)},
           'checks':{k:True for k in c.AUDIT_LEAVES},'pass':True,
           'global_k_audit':{'pass':True,'verdict':'PASS'},
           'tail_mirror_bound_integrity':{'pass':True}}
    packet={'format':c.FORMAT,'synthetic':True,'upstream_episode_provenance_verified':False,
            'fixed_design':c.fixed_design(),
            'audit':c.wrap_report('audit','audit','both',None,'fixture_c2_audit',audit),
            'design':{'matched':{},'semantic':{},'independent':{}},'calibration':{}}
    for cid in c.CANDIDATES:
        packet['design']['matched'][cid]={}
        packet['design']['semantic'][cid]={}
        packet['design']['independent'][cid]=independent(cid,'design','both')
        packet['calibration'][cid]={}
        for split in c.SPLITS:
            ns=f'fixture_c2_design_{split}_matched'
            report={'candidate':cid,'corpus':ns,'n_blocks':40,
                    'block_table':block_table(ns,40,reverse=reverse_design),
                    'density_gates':density(),'semantics':structure()}
            # Intentionally bad matched cue diagnostics: must NOT disqualify.
            report['semantics']['candidate_cue_semantics_r17_cluster_aware'] = {
                'pass':False, 'candidate':cid, 'diagnostic_only_in_new_consumer':True}
            packet['design']['matched'][cid][split]=c.wrap_report(
                'design_matched','design',split,cid,ns,report)
            packet['design']['semantic'][cid][split]=semantic(cid,'design',split)
            ns=f'fixture_c2_calibration_{split}_matched_{cid}'
            native={'seed_namespace':ns,'n_blocks':10,'block_table':block_table(ns,10)}
            packet['calibration'][cid][split] = {
                'matched':c.wrap_report('matched','calibration',split,cid,ns,native),
                'matched_conditions':{'semantics':structure(),'density_gates':density()},
                'semantic':semantic(cid,'calibration',split),
                'independent':independent(cid,'calibration',split)}
    return packet


def resign(node):
    node['payload_sha256']=c.digest(node['payload'])
