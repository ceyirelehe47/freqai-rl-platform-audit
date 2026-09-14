"""Real-project consumer integration tests (no importorskip or gate mocks).

Reports are synthetic table specimens, not real generator/audit/V2 output.
The reducer calls the installed R4/R5/R6/R17 primitives and actual selector.
"""
from __future__ import annotations
import ast
import copy
import inspect
import math
import pytest
from rl_curriculum import curriculum261_r17_c2_consumer as c
from r17_c2_consumer_fixtures import make_packet, block_table, resign, semantic


@pytest.fixture(scope='module')
def healthy_result():
    return c.consume(make_packet())


def test_full_report_chain_real_primitives(healthy_result):
    out=healthy_result
    assert out['engineering_complete'] is True
    assert out['fixture_gate_outcome']=='PASS'
    assert out['design']['selection']['candidate_id']=='historical'
    assert out['design']['selection']['n_blocks']==10
    assert out['calibration']['strict_and'] is True
    assert out['business_statistics']=='NOT_RUN'
    assert out['formal_qualification']=='NOT_ISSUED'
    assert out['formal_parameter_pack_created'] is False
    assert out['launch_authorized'] is False
    assert out['upstream_episode_provenance_rebuilt'] is False
    assert out['cue_bootstrap_and_global_k_reexecuted'] is False
    assert out['trace'].index('design/mechanical_selection') < out['trace'].index('calibration/main')


def test_deterministic_without_mutating_input(healthy_result):
    p=make_packet(); original=c.canonical(p)
    assert c.consume(p)==healthy_result
    assert c.canonical(p)==original


def test_actual_selector_is_single_ordering_authority(healthy_result):
    from rl_curriculum.curriculum261_r6_design import mechanical_selection
    t=healthy_result['design']['candidate_results']
    assert mechanical_selection(t)==('historical',10)
    # Result must not take a forced choice from unrelated packet fields.
    p=make_packet(); p['requested_candidate']='midpoint'; p['requested_n']=20
    assert c.consume(p)['design']['selection']==healthy_result['design']['selection']


def test_design_numeric_differential_against_existing_r17_segment():
    """Execute the unmodified producer's per_n AST segment as the reference.

    Only the segment after block-table creation and before density/semantics is
    executed. No evaluation, generation or fake statistical function is used.
    """
    from rl_curriculum import curriculum261_r17_design as d
    table=block_table('fixture_c2_diff',40)
    fn=ast.parse(inspect.getsource(d._evaluate_candidate_matched_r17)).body[0]
    # Native segment: rungs assignment ... per_n loop. Source shape pinned by test.
    start=next(i for i,s in enumerate(fn.body) if isinstance(s,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id=='rungs' for t in s.targets))
    end=next(i for i,s in enumerate(fn.body) if isinstance(s,ast.AnnAssign)
             and isinstance(s.target,ast.Name) and s.target.id=='density_summaries')
    ns=dict(d.__dict__); ns['block_table']=table
    exec(compile(ast.fix_missing_locations(ast.Module(body=fn.body[start:end],type_ignores=[])),
                 inspect.getsourcefile(d) or '<r17>', 'exec'),ns)
    assert c.design_statistics(table)==ns['per_n']


def test_matched_gap_uses_blockwise_se(healthy_result):
    import numpy as np
    from rl_curriculum.curriculum261_r6_pairs import c2_matched_conditions
    b=block_table('fixture_c2_se',10)
    native=c2_matched_conditions(b)
    values=np.asarray([r['gaps']['D0-D1'] for r in b['rows']])
    assert native['gaps']['D0-D1']['se']==pytest.approx(values.std(ddof=1)/math.sqrt(10))
    a=np.asarray([r['pair_metrics']['D0']['difficulty'] for r in b['rows']])
    z=np.asarray([r['pair_metrics']['D1']['difficulty'] for r in b['rows']])
    assert values.std(ddof=1)/math.sqrt(10) < math.sqrt((a.var(ddof=1)+z.var(ddof=1))/10)
    assert healthy_result['calibration']['splits']['main']['matched']['statistical']['kappa']==1.5


def test_no_qualified_combination_stops_before_calibration():
    p=make_packet(reverse_design=True); p['calibration']={'invalid_but_not_consumed':True}
    out=c.consume(p)
    assert out['engineering_complete'] is True and out['fixture_gate_outcome']=='FAIL'
    assert out['design']['selection'] is None
    assert out['design']['reason']=='no_qualified_combination'
    assert out['calibration']['status']=='NOT_RUN'
    assert not any(s.startswith('calibration/') for s in out['trace'])


@pytest.mark.parametrize('which', ['main','validation'])
def test_failed_calibration_split_never_pooled_rescued(which):
    p=make_packet()
    node=p['calibration']['historical'][which]['matched']
    ns=node['namespace']; node['payload']['block_table']=block_table(ns,10,reverse=True); resign(node)
    p['pooled']={'pass':True}
    out=c.consume(p)
    assert out['engineering_complete'] is True
    assert out['calibration']['status']=='COMPLETE'
    assert out['calibration']['splits'][which]['pass'] is False
    assert out['calibration']['strict_and'] is False
    assert out['fixture_gate_outcome']=='FAIL'
    assert out['business_statistics']=='NOT_RUN'


def test_bad_matched_point_metrics_do_not_bind(healthy_result):
    p=make_packet()
    for cid in c.CANDIDATES:
        for split in c.SPLITS:
            node=p['design']['matched'][cid][split]
            node['payload']['semantics']['candidate_cue_semantics_r17_cluster_aware']={
                'pass':True, 'per_rung':{}, 'point_recall':0., 'nonsense_diagnostic':-100.}
            resign(node)
    out=c.consume(p)
    assert out['design']['candidate_results']==healthy_result['design']['candidate_results']
    assert out['design']['selection']==healthy_result['design']['selection']


def test_dedicated_fail_does_disqualify_candidate():
    p=make_packet()
    for split in c.SPLITS:
        p['design']['semantic']['historical'][split]=semantic('historical','design',split,payoff=.07)
    out=c.consume(p)
    assert not any(out['design']['candidate_results']['historical']['qualified_by_block_count'].values())
    assert out['design']['selection']['candidate_id']!='historical'


def test_independent_point_diagnostics_do_not_bind(healthy_result):
    p=make_packet()
    for phase in ('design','calibration'):
        nodes=([p['design']['independent']['historical']] if phase=='design' else
               [p['calibration']['historical'][s]['independent'] for s in c.SPLITS])
        for node in nodes:
            node['payload']['conditions']['cue_semantics']['cue_point_diagnostics']={
                'pass':False,'point_recall':0.,'noncue_false_positive':1.,'diagnostic_only':True}
            resign(node)
    out=c.consume(p)
    assert out['fixture_gate_outcome']==healthy_result['fixture_gate_outcome']=='PASS'


def test_design_independent_structural_failure_stops_calibration():
    p=make_packet(); n=p['design']['independent']['historical']
    s=n['payload']['conditions']['cue_semantics']['structural']
    s['checks']['canonical_consistency']=False; s['pass']=False;resign(n)
    out=c.consume(p)
    assert out['design']['reason']=='design_independent_failed'
    assert out['design']['selection'] is None
    assert out['calibration']['status']=='NOT_RUN'


def test_global_k_indeterminate_stops_before_design():
    p=make_packet();a=p['audit']['payload']
    a['global_k_audit']={'pass':False,'verdict':'INDETERMINATE'}
    a['checks']['global_k_audit_pass']=False;a['checks']['global_k_audit_not_indeterminate']=False
    a['pass']=False;resign(p['audit'])
    out=c.consume(p)
    assert out['trace']==['audit'] and out['design']['selection'] is None


@pytest.mark.parametrize('mutation', [
    'production','extra_candidate','missing_candidate','changed_axis','changed_structure',
    'bad_n_option','digest','empty_blocks','duplicate_block','foreign_rung','missing_flat',
    'wrong_gap','wrong_margin','nan','bool_return','semantic_as_matched','semantic_40',
    'empty_shared_checks','empty_candidate_sides','semantic_summary_lie','wrong_producer',
    'bad_pair_count','duplicate_pair','missing_A','wrong_cal_n','cal_candidate_swap',
    'independent_bad_digest','string_boolean','claimed_episode_provenance',
])
def test_malformed_evidence_is_engineering_error(mutation):
    p=make_packet(); node=p['design']['matched']['historical']['main']; b=node['payload']['block_table']
    sem=p['design']['semantic']['historical']['main']; ind=p['design']['independent']['historical']
    if mutation=='production': p['synthetic']=False
    elif mutation=='extra_candidate': p['design']['matched']['fourth']=copy.deepcopy(p['design']['matched']['historical'])
    elif mutation=='missing_candidate': del p['design']['matched']['midpoint']
    elif mutation=='changed_axis':p['fixed_design']['ladders']['midpoint']['D3']['alpha_bps']=31.
    elif mutation=='changed_structure':p['fixed_design']['ladders']['historical']['D0']['vol_bps']=99.
    elif mutation=='bad_n_option':p['fixed_design']['literal']['n_options']=[10,15,25]
    elif mutation=='digest':node['payload_sha256']='aa'*32
    elif mutation=='empty_blocks':b['rows']=[];resign(node)
    elif mutation=='duplicate_block':b['rows'][1]['block_index']=0;resign(node)
    elif mutation=='foreign_rung':b['rows'][0]['pair_metrics']['D4']=b['rows'][0]['pair_metrics']['D3'];resign(node)
    elif mutation=='missing_flat':del b['rows'][0]['pair_metrics']['D0']['returns']['always_flat'];resign(node)
    elif mutation=='wrong_gap':b['rows'][0]['gaps']['D0-D1']=9.;resign(node)
    elif mutation=='wrong_margin':b['rows'][0]['pair_metrics']['D0']['margins']['always_long']=9.;resign(node)
    elif mutation=='nan':b['rows'][0]['pair_metrics']['D0']['returns']['reference']=float('nan')
    elif mutation=='bool_return':b['rows'][0]['pair_metrics']['D0']['returns']['oracle']=True;resign(node)
    elif mutation=='semantic_as_matched':sem['kind']='design_matched'
    elif mutation=='semantic_40':sem['payload']['n_blocks']=40;resign(sem)
    elif mutation=='empty_shared_checks':sem['payload']['shared']['checks']={};resign(sem)
    elif mutation=='empty_candidate_sides':sem['payload']['candidate']['per_rung']['D0']['sides']={};resign(sem)
    elif mutation=='semantic_summary_lie':sem['payload']['shared']['recall']['bound']=.01;resign(sem)
    elif mutation=='wrong_producer':sem['producer_interface']='unknown'
    elif mutation=='bad_pair_count':ind['payload']['report']['pair_table']['n_pairs']=79;resign(ind)
    elif mutation=='duplicate_pair':ind['payload']['report']['pair_table']['rows'][4]=copy.deepcopy(ind['payload']['report']['pair_table']['rows'][0]);resign(ind)
    elif mutation=='missing_A':del ind['payload']['report']['pair_table']['rows'][0]['episode_hashes']['A'];resign(ind)
    elif mutation=='wrong_cal_n':n=p['calibration']['historical']['main']['matched'];n['payload']['n_blocks']=20;resign(n)
    elif mutation=='cal_candidate_swap':p['calibration']['historical']['main']['matched']['candidate']='midpoint'
    elif mutation=='independent_bad_digest':ind['payload_sha256']='ab'*32
    elif mutation=='string_boolean':sem['payload']['shared']['checks']['coverage_complete']='true';resign(sem)
    elif mutation=='claimed_episode_provenance':p['upstream_episode_provenance_verified']=True
    else:raise AssertionError(mutation)
    with pytest.raises(c.InputError):c.consume(p)


def test_dedicated_shared_fail_short_circuits_candidates():
    p=make_packet();n=p['design']['semantic']['historical']['main'];s=n['payload']['shared']
    s['checks']['noise_replay_integrity']=False;s['pass']=False;n['payload']['pass']=False;resign(n)
    out=c.consume(p)
    assert out['design']['reason']=='dedicated_shared_gate_failed'
    assert not any('/matched/' in s for s in out['trace'])


def test_known_selector_tie_order_real_function():
    from rl_curriculum.curriculum261_r6_design import mechanical_selection
    table={cid:{'qualified_by_block_count':{'10':True,'15':True,'20':True},
                'maximin_score_by_qualified_n':{'10':1.,'15':100.,'20':200.},
                'param_distance_from_historical':0.5} for cid in c.CANDIDATES}
    assert mechanical_selection(table)==('conservative',10)
    table['midpoint']['maximin_score_by_qualified_n']['10']=1.1
    assert mechanical_selection(table)==('midpoint',10)
    table['midpoint']['maximin_score_by_qualified_n']['10']=1.
    table['historical']['param_distance_from_historical']=0.
    assert mechanical_selection(table)==('historical',10)


def test_no_calling_production_entrypoints():
    """Source-level tripwire in addition to WSL invocation sentinels in runbook."""
    tree=ast.parse(inspect.getsource(c))
    forbidden={'generate_pair','generate_pair_with_attempts','generate_matched_block_with_attempts',
               'run_design_stage_r17','fit_preprocessor_v2_from_bank_r17','run_policy_episode',
               'consume_production_claim','write_selected_pack_r17','mark_design_data_started'}
    calls={n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    calls|={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not calls & forbidden


@pytest.mark.parametrize('mutation', [
    'recall_gt_one', 'noncue_negative', 'precision_gt_one', 'payoff_negative',
    'fractional_count', 'bool_trades', 'negative_trades', 'rate_gt_one',
])
def test_invalid_semantic_or_density_numbers_rejected(mutation):
    packet=make_packet()
    sem=packet['design']['semantic']['historical']['main']
    matched=packet['design']['matched']['historical']['main']
    if mutation=='recall_gt_one':sem['payload']['shared']['recall']['bound']=1.1
    elif mutation=='noncue_negative':sem['payload']['shared']['noncue_false_positive']['bound']=-.1
    elif mutation=='precision_gt_one':sem['payload']['candidate']['per_rung']['D0']['sides']['A']['cue_precision']['bound']=1.1
    elif mutation=='payoff_negative':sem['payload']['candidate']['per_rung']['D0']['sides']['A']['payoff_false_cue']['bound']=-.1
    elif mutation=='fractional_count':sem['payload']['shared']['n_unique_positive_cues']=4000.5
    elif mutation=='bool_trades':matched['payload']['density_gates']['D0']['median_reference_trades_per_episode']=True
    elif mutation=='negative_trades':matched['payload']['density_gates']['D0']['median_reference_trades_per_episode']=-10.
    elif mutation=='rate_gt_one':matched['payload']['density_gates']['D0']['reference_long_label_rate']=1.1
    resign(sem);resign(matched)
    with pytest.raises(c.InputError):c.consume(packet)
