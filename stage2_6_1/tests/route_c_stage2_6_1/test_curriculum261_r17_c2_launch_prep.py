"""C2 launch 准备测试(C01-C09;调用真实 selector 的行为差分,零生成、
零调用;任务 R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2)。

机械顺序 PASS 由对 r6_design.mechanical_selection(唯一权威排序实现)
的合成结果表行为差分决定;源码字符串扫描只作诊断(B5)。
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve()
for base in HERE.parents:
    src = base / 'src'
    if (src / 'rl_curriculum' / 'curriculum261_c2.py').is_file():
        sys.path.insert(0, str(src))
        break
else:
    pytest.importorskip('rl_curriculum')
# 零调用哨兵需要安装到 runner 治理模块(claim 接口);显式加入 path。
for base in HERE.parents:
    for runner in (base / 'runner', base / 'stage2_6_1' / 'runner',
                   base / 'stage2_6_1_runner'):
        if (runner / 'r17_v2_c13_profile.py').is_file():
            if str(runner) not in sys.path:
                sys.path.insert(0, str(runner))
            break
    else:
        continue
    break

import importlib.util


def _load_prep():
    """显式从部署 src 文件加载 prep 模块。

    WSL 部署树对新写入的包内子模块存在 import 发现延迟(旧子模块
    正常、当日新文件在独立进程内稳定不被包 FileFinder 发现);测试
    用 spec_from_file_location 显式加载,模块代码与差分逻辑照常真实
    执行,不受发现机制影响。
    """
    for base in HERE.parents:
        path = base / 'src' / 'rl_curriculum' / (
            'curriculum261_r17_c2_launch_prep.py')
        if path.is_file():
            spec = importlib.util.spec_from_file_location(
                'rl_curriculum.curriculum261_r17_c2_launch_prep', path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    pytest.fail('c2 launch prep module not found in this layout')


prep = _load_prep()


def test_c01_candidate_set_exactly_three():
    d = prep.diff_against_fixed_design()
    assert d['all_pass'] is True, json.dumps(d['checks'])
    cands = prep.next_calibration_candidates()
    assert set(cands) == {'historical', 'conservative', 'midpoint'}
    # 逐字一致(固定设计字面值)。
    lit = prep.FIXED_DESIGN_LITERAL['candidates']
    for cid, ladder in cands.items():
        for i, r in enumerate(('D0', 'D1', 'D2', 'D3')):
            assert ladder[r]['alpha_bps'] == lit[cid]['alpha_bps'][i]
            assert ladder[r]['wick_kappa'] == lit[cid]['wick_kappa'][i]
    # 键集与历史逐位一致(白名单覆盖之外无结构改动)。
    from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS

    for cid, ladder in cands.items():
        for r in ('D0', 'D1', 'D2', 'D3'):
            assert set(ladder[r]) == set(C2_RUNG_PARAMS[r])
            for k, v in C2_RUNG_PARAMS[r].items():
                if k not in ('alpha_bps', 'wick_kappa'):
                    assert ladder[r][k] == v


def test_c02_n_options_and_input_contract_rejections():
    """C02:n 恰好 10/15/20;第四 n/缺候选由固定输入合同拒绝。"""
    d = prep.diff_against_fixed_design()
    assert d['n_options'] == [10, 15, 20]
    assert prep.FIXED_DESIGN_LITERAL['mechanical_order'] == [
        'minimum_qualifying_n', 'maximin',
        'minimum_distance_to_historical', 'stable_candidate_id']
    behavior = d['selector_behavior']
    assert behavior['scenarios']['fixed_inputs_n_options_exact'] is True
    assert behavior['scenarios'][
        'fixed_inputs_exactly_three_candidates'] is True


def test_c03_real_selector_behavior_differential():
    """C03-C08:调用现存权威 selector 的行为差分全部通过。"""
    d = prep.diff_against_fixed_design()
    assert d['all_pass'] is True, json.dumps(d['selector_behavior'])
    s = d['selector_behavior']
    assert s['selector'] == (
        'rl_curriculum.curriculum261_r6_design.mechanical_selection')
    # 最小合格 n 压过更高 n 的更高 score(C03)。
    assert s['scenarios']['min_qualifying_n_beats_higher_score'] is True
    # 同 n maximin 决胜(C04)。
    assert s['scenarios']['same_n_maximin_decides'] is True
    # maximin 同分 → 距 historical;再同分 → 稳定 id(C05)。
    assert s['scenarios']['maximin_tie_distance_decides'] is True
    assert s['scenarios']['distance_tie_stable_id_decides'] is True
    # 不合格项排除;全不合格明确 no-selection 不回退 control(C06)。
    assert s['scenarios']['unqualified_never_selected'] is True
    assert s['scenarios']['all_unqualified_no_selection'] is True
    # 输入顺序打乱不变(C07)。
    assert s['scenarios']['input_order_invariant'] is True
    # matched/point diagnostics 不改变 verdict(C08)。
    assert s['scenarios'][
        'diagnostic_keys_do_not_change_verdict'] is True
    # 直接调用权威 selector 复核最小 n 优先(独立于 prep 断言)。
    from rl_curriculum.curriculum261_r6_design import mechanical_selection

    table = prep._table(
        {'alpha': {10: True, 15: True}, 'beta': {10: False, 15: True}},
        {'alpha': {10: 1.0, 15: 2.0}, 'beta': {15: 50.0}},
        {'alpha': 0.9, 'beta': 0.1})
    assert mechanical_selection(table) == ('alpha', 10)
    all_unq = prep._table(
        {'alpha': {10: False, 15: False, 20: False},
         'beta': {10: False, 15: False, 20: False}},
        {'alpha': {}, 'beta': {}}, {'alpha': 0.0, 'beta': 0.0})
    assert mechanical_selection(all_unq) == (None, None)


def test_c03_binding_sources_dedicated_only():
    d = prep.diff_against_fixed_design()
    assert d['binding_sources'] == {
        'dedicated_semantic_blocks': 160,
        'cue_audit_blocks_per_corpus': 500}
    assert d['checks']['semantic_160'] is True
    assert d['checks']['cue_audit_500_plus_500'] is True


def test_c04_r16_fail_and_control_not_selection():
    """R16 失败保留;v2 工程 historical control 不等于 design 选择。"""
    from rl_curriculum.curriculum261_r6_param_pack import (
        C2_LADDER_CANDIDATES,
    )

    # v2 工程 run 的控制候选仍是网格成员(工程身份未伪装成选择)。
    assert 'c2l_historical_control' in C2_LADDER_CANDIDATES
    cands = prep.next_calibration_candidates()
    assert cands['historical'] == C2_LADDER_CANDIDATES[
        'c2l_historical_control']
    assert prep.diff_against_fixed_design()['checks'][
        'r16_fail_retained'] is True


def test_c05_no_namespace_claim_or_plan_registered():
    """本轮不注册新 namespace/claim/正式 plan(准备件只含草案标记)。"""
    assert prep.NOT_AUTHORIZED is True
    src = Path(prep.__file__).read_text(encoding='utf-8')
    assert 'namespace' in src  # 文档提及允许
    # prep 模块不定义任何 namespace 常量/写盘函数。
    assert 'NAMESPACE' not in src.replace(
        '不注册任何 namespace', '').replace(
        '本轮不注册新 namespace', '')
    for banned in ('def write_', 'def persist_', 'def generate_',
                   'def run_'):
        assert banned not in src


def test_c06_c09_zero_call_sentinels_all_zero():
    """C09:generator/fit/eval/canonical/policy/claim/namespace 哨兵
    计数全 0;哨兵全部安装成功(fail-closed,无不可用项)。"""
    d = prep.diff_against_fixed_design()
    behavior = d['selector_behavior']
    assert behavior['all_pass'] is True
    zero = behavior['zero_call']
    assert zero['all_zero'] is True, json.dumps(zero)
    assert zero['unavailable_sentinels'] == []
    assert zero['violations'] == []
    assert all(v == 0 for v in zero['counts'].values())
    interfaces = {'generator', 'fit', 'eval', 'policy', 'canonical',
                  'claim', 'namespace'}
    seen = {key.split(':')[0] for key in zero['counts']}
    assert interfaces <= seen, seen
    # 源码字符串扫描仅诊断,不再是 PASS 决定面。
    assert isinstance(behavior['diagnostics_only_source_scan'], dict)


def test_c06_generation_sentinels_on_entry_points(monkeypatch, tmp_path):
    """全部 prep 入口对生产生成/fit/eval/canonical/policy 零调用。"""
    import rl_curriculum.curriculum261_api as api
    import rl_curriculum.curriculum261_pairs as pairs

    boom = RuntimeError('generation sentinel tripped')

    def fail(*a, **kw):
        raise boom

    monkeypatch.setattr(api, 'generate_pair_with_attempts', fail)
    monkeypatch.setattr(pairs, 'generate_pair', fail)
    # diff/candidates/行为差分三次调用全部完成且不触发哨兵。
    d = prep.diff_against_fixed_design()
    assert d['all_pass'] is True
    assert len(prep.next_calibration_candidates()) == 3
    assert prep.verify_mechanical_selection_behavior()['all_pass'] is True
