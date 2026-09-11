#!/usr/bin/env python3
"""Profile-driven finite-reserve assembly for R17 V2 C1/C3 calibration.

Reuses the v1 reserve batch discipline (create-only evidence journals,
single schedule source, complete proof classification before any member
is consumed) but is driven entirely by the immutable
R17V2C13EngineeringCalibration-v1 profile: three families for fit banks,
two families for eval corpora, C3-only bounded reserve (fit p6/p7,
eval p10/p11).

Generation and evaluation remain strictly separated: this module only
generates, classifies and seals stage membership. Fitting, routing and
scaled evaluation live in r17_v2_c13_pipeline.py.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import sys
from typing import Any

from r17_v2_c13_profile import (
    C3_ALLOWED_REJECTIONS, FAMILY_C3, RUNGS, canonical, digest, require,
    request_key, stage_requests,
)


def envelope_digest(env: dict, call: bool = False) -> str:
    # Persisted JSON subset of the authoritative generation-envelope contract.
    return ('r11call-' if call else 'r11env-') + digest(
        {k: v for k, v in env.items() if k not in ('digest', 'runtime')})


def file_meta(path: Path) -> dict:
    import hashlib
    import os

    before = path.stat()
    h = hashlib.sha256()
    n = 0
    with path.open('rb') as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            n += len(chunk)
    after = path.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size,
                          s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after) and n == after.st_size,
            'file changed while reading')
    return {'bytes': n, 'sha256': h.hexdigest()}


def read_json(path: Path) -> Any:
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, f'duplicate JSON key: {k}')
            result[k] = v
        return result

    def invalid(value):
        raise ValueError(f'nonfinite JSON value: {value}')
    return json.loads(path.read_text(encoding='utf-8'),
                      object_pairs_hook=unique, parse_constant=invalid)


def new_json(path: Path, value: Any) -> None:
    """Create-only atomic write under our newly owned run tree."""
    import os

    payload = (canonical(value) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + secrets.token_hex(12) + '.tmp')
    owned = False
    try:
        with tmp.open('xb') as f:
            owned = True
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp, path)
    finally:
        if owned:
            tmp.unlink(missing_ok=True)


def tree_snapshot(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(), 'symlink not allowed in batch evidence')
        if p.is_file():
            out[p.relative_to(root).as_posix()] = file_meta(p)
        else:
            require(p.is_dir(), 'nonregular evidence object')
    return out


@dataclass
class Generated:
    proof: dict
    handle: Any = None


# ------------------------------------------------------------- scheduling
class StageCursor:
    """Single schedule source for one stage (execution and cold readback)."""

    def __init__(self, stage: dict[str, Any]):
        self.stage = stage
        self.quota = stage['quota_per_stratum']
        reserve = stage['reserve_indices'].get(FAMILY_C3, [])
        self.last_index = {
            family: (self.quota + len(reserve) - 1 if family == FAMILY_C3
                     else self.quota - 1)
            for family in stage['families']}
        self.all = stage_requests(stage)
        self.pos = 0
        self.counts = {(f, r): 0 for f in stage['families'] for r in RUNGS}
        self.states = {request_key(q): 'not_started' for q in self.all}
        self.selected: list[str] = []
        self.attempted: list[str] = []
        self.stop = None

    def next(self) -> dict[str, Any] | None:
        if self.stop:
            return None
        while self.pos < len(self.all):
            q = self.all[self.pos]
            if self.counts[(q['family'], q['rung'])] == self.quota:
                self.states[request_key(q)] = 'not_needed'
                self.pos += 1
                continue
            return q
        return None

    def consume(self, q: dict[str, Any], status: str) -> None:
        require(self.next() == q, 'out-of-order/unapproved request')
        require(status in ('accepted', 'structural_rejected', 'fatal'),
                'unknown request result')
        key = request_key(q)
        self.attempted.append(key)
        self.states[key] = status
        self.pos += 1
        if status == 'accepted':
            self.counts[(q['family'], q['rung'])] += 1
            self.selected.append(key)
        elif status == 'fatal':
            self.stop = 'fatal'
        elif q['family'] != FAMILY_C3:
            # C1/C2 hold no reserve rights: any rejection stops the run.
            self.stop = 'fatal_non_c3_rejection'
        if (q['pair_index'] == self.last_index[q['family']]
                and self.counts[(q['family'], q['rung'])] < self.quota
                and self.stop is None):
            self.stop = 'reserve_exhausted'

    def snapshot(self) -> dict:
        self.next()  # mark skipped reserves after the last accepted slot
        return {'stage': self.stage['stage'],
                'attempted': list(self.attempted),
                'selected': list(self.selected),
                'states': dict(self.states), 'stop': self.stop,
                'quota_filled': all(
                    n == self.quota for n in self.counts.values())}


# ---------------------------------------------------------- proof checks
def expected_seed(q: dict[str, Any], attempt: int) -> int:
    import hashlib

    fields = ['stage2_6_1', q['namespace'], q['family'], q['rung'],
              q['pair_index'], attempt]
    return int.from_bytes(hashlib.sha256(
        canonical(fields).encode()).digest()[:8], 'big')


def _c3_count_backed_reasons(env: dict) -> None:
    """C3-only: rejection reasons must be backed by the event table."""
    reasons = env.get('rejection_reasons')
    counts = {scope: env['event_table'][scope]['counts']
              for scope in ('A', 'B')}
    for label, side in (('A', 'A'), ('B', 'B'), ('pair', 'A')):
        c = counts[side]
        expected_flags = {
            'too_few_signals': c['n_signals'] < 6,
            'too_few_distractors': c['n_distractors'] < 1,
            'too_few_below_cost_signals': c['n_below_cost'] < 2,
            'too_few_above_cost_signals': (
                c['n_above_cost'] < 2 if side == 'A'
                else c['n_above_cost'] != 0),
        }
        for code, should_fail in expected_flags.items():
            require((label + ':' + code in reasons) == should_fail,
                    'count/rejection-reason contradiction')


def validate_proof(q: dict[str, Any], proof: dict, params_snapshot: dict,
                   runtime: dict) -> str:
    """Classify only complete, identity-bound proof.

    Generic checks apply to all three families; the C3 count-backed
    reason audit applies only to c3_cost (the only family with reserve
    rights). Unknown reasons for C3 and any rejection for C1/C2 are
    reported as-is — the scheduler turns them into a fatal stop.

    v2 修复(B1):generator 身份按请求 family 从 runtime['generators']
    取期望值——call 与每条 attempt 都必须匹配该族真实身份;缺映射、
    旧式单身份 runtime(v1 形态)与跨族摘要均拒绝,不 fallback。
    """
    import re

    require(proof['coordinate'] == q,
            'request identity mismatch')
    generators = runtime.get('generators')
    require(isinstance(generators, dict)
            and q['family'] in generators,
            f"runtime generator map missing family: {q['family']}")
    expected_generator = generators[q['family']]
    require(proof['status'] in ('accepted', 'structural_rejected'),
            'unknown generation status')
    require(proof.get('recorder_errors') == [],
            'recorder errors or missing recorder fact')
    call = proof['call_envelope']
    require(call['digest'] == envelope_digest(call, True),
            'call envelope digest mismatch')
    for k in ('namespace', 'family', 'rung', 'pair_index'):
        require(call.get(k) == q[k] and type(call.get(k)) is type(q[k]),
                f'call {k} mismatch')
    rp = {**params_snapshot['rung_params'][q['family']][q['rung']],
          'cur261_rung': q['rung']}
    require(call.get('rung_params') == rp
            and call.get('max_attempts') == 5,
            'call params or attempts changed')
    require(call.get('iteration') == 'r17', 'call iteration mismatch')
    require(call.get('generator') == expected_generator,
            'generator identity mismatch')
    require(call.get('split') == 'curriculum261_' + q['namespace']
            and call.get('timeframe') == '15m',
            'call split/timeframe mismatch')
    log, envs = proof['attempt_log'], proof['attempt_envelopes']
    for k in ('family', 'rung', 'pair_index'):
        require(log.get(k) == q[k], 'attempt log coordinate mismatch')
    require(log.get('seed_namespace') == q['namespace']
            and log.get('max_attempts') == 5,
            'attempt log namespace/budget mismatch')
    require(isinstance(envs, list) and 1 <= len(envs) <= 5,
            'attempt evidence missing/outside budget')
    accepted = proof['status'] == 'accepted'
    selected = len(envs) - 1 if accepted else None
    require(type(log.get('selected_attempt')) is (
        int if accepted else type(None)), 'selected type invalid')
    require(log.get('selected_attempt') == selected,
            'first-pass selection mismatch')
    require(accepted or len(envs) == 5,
            'rejection must exhaust exactly five attempts')
    require(len(log['attempts']) == len(envs), 'log/envelope length mismatch')
    for i, (env, att) in enumerate(zip(envs, log['attempts'])):
        require(type(env.get('attempt_index')) is int
                and type(att.get('index')) is int
                and env['attempt_index'] == i and att['index'] == i,
                'attempt order mismatch')
        require(env['digest'] == envelope_digest(env),
                'attempt digest mismatch')
        for k in ('namespace', 'family', 'rung', 'pair_index'):
            require(env.get(k) == q[k], f'envelope {k} mismatch')
        require(env.get('generator') == call['generator'],
                'attempt generator mismatch')
        require(env.get('generator') == expected_generator,
                'attempt generator not bound to request family identity')
        require(env.get('iteration') == 'r17'
                and env.get('split') == call['split']
                and env.get('timeframe') == '15m',
                'attempt phase/timeframe mismatch')
        require(type(env.get('outer_seed')) is int
                and env['outer_seed'] == expected_seed(q, i),
                'outer seed mismatch')
        require(type(env.get('internal_derived_seed')) is int
                and env['internal_derived_seed'] >= 0,
                'internal seed missing')
        require(env.get('seed_derivation_fields') == {
            **{k: q[k] for k in ('namespace', 'family', 'rung',
                                 'pair_index')},
            'attempt': i, 'stage_id': 'stage2_6_1'},
            'seed fields mismatch')
        require(env.get('exception') is None,
                'generator exception is not reserve-eligible')
        require(env.get('generator_state_changed') is False
                and env.get(
                    'generator_state_changed_since_call_start') is False,
                'generator state drift')
        passed = accepted and i == selected
        require(env.get('accepted') is passed
                and att.get('accepted') is passed,
                'acceptance contradiction')
        reasons = env.get('rejection_reasons')
        require(isinstance(reasons, list)
                and env.get('structural_validator_results') == reasons,
                'structural reason mismatch')
        if passed:
            require(reasons == [] and att.get('reason') == '',
                    'accepted attempt has rejection reasons')
        else:
            require(bool(reasons)
                    and all(isinstance(x, str) for x in reasons),
                    'empty rejection on failed attempt')
            if q['family'] == FAMILY_C3:
                require(all(x in C3_ALLOWED_REJECTIONS for x in reasons),
                        'non-whitelisted C3 rejection: stop instead of '
                        'substitute')
            require(att.get('reason') == '; '.join(reasons),
                    'log reasons mismatch')
        for side in ('A', 'B'):
            bp = env['base_params'][side]
            expected_params = {**rp, 'pair_variant': side,
                               'episode_bars': 288, 'initial_price': 1.0}
            require(set(bp) == set(expected_params),
                    'undeclared generator override or missing base parameter')
            for k, v in expected_params.items():
                require(k in bp and bp[k] == v
                        and not isinstance(bp[k], bool),
                        f'base param missing/changed: {side}.{k}')
            table = env['event_table'][side]
            require(table['bars'] == 288
                    and isinstance(table['hidden_digest'], str)
                    and bool(table['hidden_digest']),
                    'incomplete event table')
            require(isinstance(table['episode_content_hash'], str)
                    and re.fullmatch(r'ce-[a-f0-9]{64}',
                                     table['episode_content_hash'])
                    is not None,
                    'episode content hash invalid')
            if q['family'] == FAMILY_C3:
                counts = table['counts']
                for k in ('n_signals', 'n_above_cost', 'n_below_cost',
                          'n_distractors'):
                    require(type(counts.get(k)) is int
                            and 0 <= counts[k] <= 288,
                            'missing/invalid C3 counts')
                require(counts['n_above_cost'] + counts['n_below_cost']
                        == counts['n_signals'],
                        'inconsistent signal counts')
                if passed:
                    require(counts['n_signals'] >= 6
                            and counts['n_below_cost'] >= 2
                            and counts['n_distractors'] >= 1,
                            'accepted sample violates C3 counts')
                    require(counts['n_above_cost'] >= 2 if side == 'A'
                            else counts['n_above_cost'] == 0,
                            'accepted cost structure invalid')
        if q['family'] == FAMILY_C3 and not passed:
            _c3_count_backed_reasons(env)
    if accepted:
        hashes = {s: envs[-1]['event_table'][s]['episode_content_hash']
                  for s in ('A', 'B')}
        require(proof.get('episode_hashes') == hashes
                == log.get('output_episode_hashes'),
                'selected envelope/output identity mismatch')
        integrity = proof.get('integrity')
        require(isinstance(integrity, dict)
                and integrity.get('pass') is True,
                'integrity failure is fatal, not eligible for reserve')
        for k in ('family', 'rung', 'pair_index'):
            require(integrity.get(k) == q[k], 'integrity identity mismatch')
    else:
        require(log.get('output_episode_hashes') == {}
                and proof.get('episode_hashes') == {},
                'rejected request has selected output')
    return proof['status']


# ------------------------------------------------------------ real backend
def ensure_imports() -> None:
    try:
        import rl_curriculum.curriculum261_api  # noqa: F401
    except ModuleNotFoundError as exc:
        if exc.name not in ('rl_curriculum',
                            'rl_curriculum.curriculum261_api'):
            raise
        src = Path(__file__).resolve().parent.parent / 'src'
        if not src.is_dir():
            raise
        sys.path.insert(0, str(src))


class RealBackend:
    """Three-family generation via the unchanged production API."""

    def __init__(self, params_snapshot: dict):
        ensure_imports()
        from rl_curriculum import curriculum261_api as api
        from rl_curriculum import curriculum261_pairs as pairs
        from rl_curriculum import curriculum261_generation_envelope as env
        from rl_curriculum import curriculum261_r17_registry as registry

        from r17_v2_c13_profile import (
            EVAL_NAMESPACES, FIT_NAMESPACES)
        self.api, self.pairs, self.env = api, pairs, env
        require(api.CURRICULUM261_MAX_ATTEMPTS == 5,
                'per-pair attempt contract changed')
        specs = pairs.family_specs()
        for family in ('c1_opportunity', 'c2_context', 'c3_cost'):
            spec = specs[family]
            require(spec.rung_params == specs[family].rung_params,
                    'family spec unavailable')
        # 工程参数快照与 family_specs 原值逐步对拍(D0-D2 + defaults)。
        for family, params in params_snapshot['rung_params'].items():
            for rung in ('D0', 'D1', 'D2'):
                require(params[rung] == specs[family].rung_params[rung],
                        f'{family} {rung} snapshot deviates from baseline')
            require(params_snapshot['reference_defaults'][family]
                    == dict(specs[family].reference_defaults),
                    f'{family} reference defaults deviate')
        for ns in (*FIT_NAMESPACES.values(), *EVAL_NAMESPACES.values()):
            require(ns in api.CURRICULUM261_R17_NAMESPACES
                    and ns in registry.R17_ALL_NAMESPACES,
                    'engineering namespaces not installed')
            require(ns not in api.CURRICULUM261_R17_FORMAL_NAMESPACES,
                    'engineering namespace became formal')
        self.params_snapshot = params_snapshot
        # 治理 v2(P03):执行面改用本轮治理闭包 lock;历史 v2 主 run
        # 执行闭包(r17_v2_c13_source_lock.py,d3cdf3d1 字节)只读保留,
        # 不再给新代码背书。
        from r17_v2_c13_governance_source_lock import SOURCE_SHA256
        import importlib
        self.source_identity = {}
        for name, expected in SOURCE_SHA256.items():
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve(strict=True)
            got = file_meta(path)['sha256']
            require(got == expected,
                    f'actual imported source drift: {name} ({path})')
            self.source_identity[name] = {'path': str(path), 'sha256': got}

    def describe(self) -> dict:
        """三族各自绑定真实 generator 身份(v2 修复 B1)。

        v1 缺陷:此处只登记 FAMILY_C3 的身份,validate_proof 对所有
        请求用该单一身份比较——首个 C1 请求必然 mismatch。v2 按 family
        建立完整映射;三族身份必须彼此不同,缺族/重复/错绑在 claim 前
        拒绝(任务书 WP1.1/WP1.4)。
        """
        specs = self.pairs.family_specs()
        generators = {
            family: self.env.generator_identity(specs[family].generator)
            for family in ('c1_opportunity', 'c2_context', 'c3_cost')
        }
        require(set(generators) == set(self.params_snapshot[
            'rung_params']), 'generator map must cover exactly the '
            'three schedule families')
        digests = {family: g.get('fingerprint') or g
                   for family, g in generators.items()}
        require(all(d for d in digests.values())
                and len(set(map(str, digests.values()))) == 3,
                'the three families must carry distinct generator '
                'identities')
        return {'kind': 'real',
                'generators': generators,
                'sources': self.source_identity,
                'interpreter': sys.version,
                'families': ['c1_opportunity', 'c2_context', 'c3_cost'],
                'evaluation': 'existing evaluate_pair_corpus_r4 with '
                              'reloaded V2 (scaled production path)',
                'normalization_fit': 'two three-curriculum unified V2 fit '
                                     'banks (engineering, not training '
                                     'qualification)'}

    def generate(self, q: dict[str, Any], observe) -> Generated:
        api, pairs, env = self.api, self.pairs, self.env
        spec = pairs.family_specs()[q['family']]
        params = {**self.params_snapshot['rung_params'][
            q['family']][q['rung']], 'cur261_rung': q['rung']}

        class Recorder(env.EnvelopeRecorder):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.failures = []

            def record(self, event, payload):
                try:
                    super().record(event, payload)
                    if event == 'attempt':
                        observe('attempt', self.attempt_envelopes[-1])
                except Exception as exc:
                    # Upstream swallows recorder errors; we preserve them
                    # and fail the batch after this pair. They never
                    # authorize a reserve.
                    self.failures.append(
                        f'{type(exc).__name__}: {str(exc)[:1000]}')
                    raise

        rec = Recorder(iteration='r17', namespace=q['namespace'],
                       family=q['family'], rung=q['rung'],
                       pair_index=q['pair_index'], rung_params=params)
        observe('call', rec.call_envelope)
        try:
            episodes, log = api.generate_pair_with_attempts(
                spec.generator, params, namespace=q['namespace'],
                family=q['family'], rung=q['rung'],
                pair_index=q['pair_index'],
                structural_validator=pairs.pair_acceptance_contract(
                    q['family']), recorder=rec)
        except api.PairGenerationError as exc:
            log = exc.attempt_log
            if log is None:
                raise RuntimeError(
                    'PairGenerationError missing attempt log') from exc
            proof = {'coordinate': dict(q),
                     'status': 'structural_rejected',
                     'call_envelope': rec.call_envelope,
                     'attempt_envelopes': rec.attempt_envelopes,
                     'attempt_log': log.canonical(),
                     'episode_hashes': {},
                     'recorder_errors': rec.failures,
                     'error': str(exc)}
            return Generated(json.loads(env.canonical_json(proof)))
        # All other exceptions propagate. No catch-and-resample.
        pair = pairs.PairRecord(family=q['family'], rung=q['rung'],
                                pair_index=q['pair_index'],
                                episodes=episodes, attempt_log=log)
        pair.integrity = pairs.compute_pair_integrity(pair)
        pair.integrity_ok = pair.integrity['pass']
        proof = {'coordinate': dict(q), 'status': 'accepted',
                 'call_envelope': rec.call_envelope,
                 'attempt_envelopes': rec.attempt_envelopes,
                 'attempt_log': log.canonical(),
                 'episode_hashes': dict(log.episode_hashes),
                 'integrity': pair.integrity,
                 'recorder_errors': rec.failures}
        return Generated(json.loads(env.canonical_json(proof)), pair)


# ------------------------------------------------------------ stage runner
def read_episode_csv(path: Path) -> Any:
    """重载持久化 episode 数值输入(CSV %.17g round-trip)。

    pandas C 解析器默认路径对 float64 有 ULP 级误差;必须用
    float_precision='round_trip' 才与生成时的 episode_content_hash
    逐位一致(不修改原 hash 算法迁就 I/O——修解析,不修指纹)。
    """
    import pandas as pd

    return pd.read_csv(path, float_precision='round_trip')


def persist_selected_episode(root: Path, stage: str, q: dict[str, Any],
                             pair: Any) -> dict:
    """Persist selected numerical inputs (CSV %.17g + spec + hash 对拍).

    保存选定 pair 的 A/B episode 数值输入,后续验证无需重新生成本轮
    坐标;写后复算 episode content hash 证明与生成时逐位一致。

    治理修复(E02/E03,WP3):v2 轮只持久化 df CSV 与最小 spec,hidden
    事件表不在证据面内 —— 生产冷读无法对实际重载对象重算权威
    ``episode_content_hash``(它覆盖 spec.canonical + df + hidden),
    只能对拍 CSV 字节,等于 episode 身份层不可重建。现在补齐:

    - ``{key}_{side}.hidden.csv``:hidden 事件表数值列(同 %.17g 规范);
    - spec.json 增 split/params/timeframe/family_version/is_null/
      generator_fingerprint —— 与 EpisodeSpec.canonical() 的全部
      字段对齐;

    使 reader 可重建 GeneratedEpisode 等价对象并调用生产 hash 函数。
    旧 v2 归档无这些字段,reader 按 partial 诚实登记,不回填旧文件。
    """
    out_dir = root / 'episodes' / stage
    out_dir.mkdir(parents=True, exist_ok=True)
    key = request_key(q)
    meta = {}
    import hashlib

    def _sha(p: Path) -> str:
        h = hashlib.sha256()
        with p.open('rb') as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        return h.hexdigest()

    for side in ('A', 'B'):
        ep = pair.episodes[side]
        path = out_dir / f'{key}_{side}.csv'
        require(not path.exists(), 'episode artifact already exists')
        path.write_text(
            ep.df.to_csv(index=False, float_format='%.17g'),
            encoding='utf-8')
        hidden_path = out_dir / f'{key}_{side}.hidden.csv'
        require(not hidden_path.exists(),
                'hidden artifact already exists')
        hidden_path.write_text(
            ep.hidden.to_csv(index=False, float_format='%.17g'),
            encoding='utf-8')
        spec_path = out_dir / f'{key}_{side}.spec.json'
        new_json(spec_path, {
            'format': 'v2c13-episode-persist-v2',
            'seed': int(ep.spec.seed),
            'namespace': q['namespace'],
            'family': ep.spec.family, 'rung': q['rung'],
            'pair_index': q['pair_index'], 'side': side,
            'split': ep.spec.split,
            'timeframe': ep.spec.timeframe,
            'params': dict(ep.spec.params),
            'family_version': ep.family_version,
            'is_null': bool(ep.is_null),
            'generator_fingerprint': ep.generator_fingerprint,
        })
        meta[side] = {'csv': path.name, 'bytes': path.stat().st_size,
                      'csv_sha256': _sha(path),
                      'hidden_csv': hidden_path.name,
                      'hidden_csv_sha256': _sha(hidden_path),
                      'episode_content_hash':
                          pair.attempt_log.episode_hashes[side]}
    return meta


def execute_stage(root: Path, stage: dict[str, Any], backend,
                  params_snapshot: dict, runtime: dict
                  ) -> tuple[dict, dict[str, Any]]:
    """Generate one stage to membership closure. No evaluation here.

    Returns (stage result, handles of selected in-memory pairs). The
    caller owns the handles and must release them after fit/eval
    (resource discipline §8.3).
    """
    stage_dir = root / 'stages' / stage['stage']
    cursor = StageCursor(stage)
    handles, proofs = {}, {}
    result = {'stage': stage['stage'], 'status': 'error', 'rc': 3,
              'error': None, 'stop': None}
    index = []
    try:
        while (q := cursor.next()) is not None:
            key = request_key(q)
            new_json(stage_dir / 'starts' / (key + '.json'),
                     {'coordinate': dict(q), 'ordinal': len(index)})
            observed = []

            def observe(kind, obj):
                require(kind in ('call', 'attempt'), 'unknown recorder event')
                suffix = ('call' if kind == 'call'
                          else f"attempt_{obj['attempt_index']}")
                new_json(stage_dir / 'attempts' / key
                         / (suffix + '.json'), obj)
                observed.append((kind, obj))
            try:
                generated = backend.generate(q, observe)
                proof = generated.proof
                new_json(stage_dir / 'requests' / (key + '.json'), proof)
                status = validate_proof(q, proof, params_snapshot, runtime)
                require(observed == [
                    ('call', proof['call_envelope'])]
                    + [('attempt', e)
                       for e in proof['attempt_envelopes']],
                    'per-attempt persistence differs from final proof')
                require(not (status == 'accepted'
                             and generated.handle is None),
                        'missing accepted in-memory pair')
                if status == 'accepted':
                    episode_meta = persist_selected_episode(
                        root, stage['stage'], q, generated.handle)
                    handles[key] = generated.handle
                    proofs[key] = proof
                    result.setdefault('episode_artifacts', {})[key] = \
                        episode_meta
                index.append({'key': key, 'status': status})
                cursor.consume(q, status)
            except Exception as exc:
                index.append({'key': key, 'status': 'fatal'})
                cursor.consume(q, 'fatal')
                new_json(stage_dir / 'errors' / (key + '.json'),
                         {'type': type(exc).__name__,
                          'message': str(exc)[:2000]})
                raise
        state = cursor.snapshot()
        selection = {
            'stage': stage['stage'],
            'members': state['selected'],
            'member_coordinates': [
                dict(q) for q in stage_requests(stage)
                if request_key(q) in set(state['selected'])],
            'states': state['states'], 'stop': state['stop'],
            'quota_filled': state['quota_filled'],
            'evaluation_not_started': True}
        new_json(stage_dir / 'selection.json', selection)
        if not state['quota_filled']:
            result.update(status='reserve_exhausted', rc=4,
                          stop=state['stop'])
        else:
            result.update(status='complete', rc=0)
    except Exception as exc:
        result['error'] = {'type': type(exc).__name__,
                           'message': str(exc)[:2000]}
    result['schedule'] = cursor.snapshot()
    result['results'] = index
    new_json(stage_dir / 'result.json', result)
    return result, handles
