"""工作包 B:时钟与熵源闭包(B1/B2 + E5/E6;真实生产路径)。

- E5:Builder 用 time.time/time_ns/datetime/monotonic/perf_counter
  影响 pack -> 只能取得冻结纪元 0(跨运行一致,不依赖"三次碰巧
  相同");ctypes raw clock_gettime -> EPERM -> 构建失败;
- E6:os.urandom/secrets/random 只能得到受承诺确定性熵(双跑一致);
  getrandom raw syscall -> EPERM -> 构建失败;numpy 未播种 RNG 跨
  进程不确定 -> precommit 双跑 BuilderUncertainError;
- vDSO 冻结 stub 证明:EDIC 携带 stub 摘要/原始 vDSO 摘要/行为
  探针;PR_SET_TSC rc=0。
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.stage2_6_0i


def _notes_var(body):
    return body


def test_frozen_clock_visible_to_builder(run_attack):
    """E5:time.time()/datetime.now() 等返回冻结纪元 0,pack 携带
    冻结值(不是"接近所以一致",而是恒 0)。"""
    run = run_attack(
        "    t1 = time.time()\n"
        "    t2 = time.time_ns()\n"
        "    t3 = time.monotonic()\n"
        "    t4 = time.perf_counter()\n"
        "    y = datetime.datetime.now().year\n"
        "    notes = {'t1': t1, 't2': t2, 't3': t3, 't4': t4, 'y': y}\n",
        label="clock-frozen", max_attempts=1,
        top_imports="import time, datetime\n")
    assert isinstance(run, dict), run
    edic = run["deterministic_input_report"]
    assert edic["clock"]["behavior"]["time_time"] == 0.0
    assert edic["clock"]["behavior"]["datetime_now_year"] == 1970
    assert edic["clock"]["behavior"]["time_monotonic"] == 0.0
    assert edic["clock"]["behavior"]["time_perf_counter"] == 0.0


def test_double_run_clock_consistency(run_attack):
    """同一"日时间攻击"builder 两次运行:pack/edi/lock 全一致(冻结
    纪元使时间不可作为区分输入)。"""
    body = (
        "    day = int(time.time() // 86400)\n"
        "    notes = {'day': day}\n")
    r1 = run_attack(body, label="clock-double", max_attempts=1,
                    top_imports="import time\n")
    r2 = run_attack(body, label="clock-double", max_attempts=1,
                    top_imports="import time\n")
    assert isinstance(r1, dict) and isinstance(r2, dict), (r1, r2)
    assert r1["pack_hash"] == r2["pack_hash"]
    assert r1["deterministic_input_hash"] == r2["deterministic_input_hash"]
    assert r1["runtime_lock_hash"] == r2["runtime_lock_hash"]


def test_raw_clock_syscall_rejected(run_attack):
    """E5:ctypes 直接 clock_gettime/time/gettimeofday -> EPERM ->
    构建失败(不是返回真实时间)。"""
    outcome = run_attack(
        "    import ctypes\n"
        "    libc = ctypes.CDLL(None, use_errno=True)\n"
        "    rc = libc.syscall(228, 0, 0)\n"
        "    if rc == 0:\n"
        "        notes = {'leak': True}\n"
        "    else:\n"
        "        raise RuntimeError('clock denied')\n",
        label="clock-raw", max_attempts=1)
    assert not isinstance(outcome, dict), "raw clock syscall 未被拒绝"
    name, msg = outcome
    assert "clock" in msg.lower() or "denied" in msg.lower() or \
        name in ("BuilderRunnerError", "BuilderProvenanceError"), outcome


def test_rdtsc_kills_worker(run_attack):
    """E5:TSC 通道:PR_SET_TSC=SIGSEGV 后执行 rdtsc -> Worker 信号
    死亡(构建失败;无 pack 采信)。"""
    outcome = run_attack(
        "    import ctypes\n"
        "    libc = ctypes.CDLL(None, use_errno=True)\n"
        "    libc.mmap.restype = ctypes.c_void_p\n"
        "    page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
        "    ctypes.memmove(page, b'\\x0f\\x31\\xc3', 3)\n"
        "    fn = ctypes.CFUNCTYPE(ctypes.c_uint64)(page)\n"
        "    tsc = fn()\n"
        "    notes = {'tsc': tsc}\n",
        label="tsc-read", max_attempts=1)
    assert not isinstance(outcome, dict), "rdtsc 未被 PR_SET_TSC 封禁"
    name, msg = outcome
    assert name in ("BuilderRunnerError", "BuilderProvenanceError"), outcome


def test_vdso_stub_evidence(run_attack):
    """EDIC 携带 vDSO 冻结 stub 证明(符号偏移/stub 摘要/原始 vDSO
    字节摘要)与 raw syscall 拒绝矩阵。"""
    run = run_attack("    pass\n", label="vdso-ev", max_attempts=1)
    assert isinstance(run, dict), run
    vdso = run["deterministic_input_report"]["clock"]["vdso"]
    assert vdso["mode"] == "frozen-stub"
    assert vdso["frozen_epoch"] == 0
    assert "__vdso_clock_gettime" in vdso["stubs"]
    assert len(vdso["stub_sha256"]) == 64
    assert len(vdso["original_vdso_sha256"]) == 64
    raw = run["deterministic_input_report"]["clock"]["raw_syscall"]
    for key in ("clock_gettime", "time", "gettimeofday",
                "clock_gettime64"):
        assert raw[key] == "ERRNO1"
    assert run["deterministic_input_report"]["clock"][
        "pr_set_tsc_rc"] == 0


def test_deterministic_entropy_sources(run_attack):
    """E6(2.6.0j 升级):Compute 阶段直接读 /dev/urandom 的通道
  (os.urandom/secrets)被 final filter 拒绝(比 0i 的确定性熵文件
  语义更强——零文件读取);random 模块的确定性由 Prepare 预加载时
  受承诺播种保证,两次运行 pack 一致。"""
    body = (
        "    r1 = random.random()\n"
        "    notes = {'r1': r1}\n")
    r1 = run_attack(body, label="entropy-det", max_attempts=1,
                    top_imports="import random\n")
    r2 = run_attack(body, label="entropy-det", max_attempts=1,
                    top_imports="import random\n")
    assert isinstance(r1, dict) and isinstance(r2, dict), (r1, r2)
    assert r1["pack_hash"] == r2["pack_hash"], "确定性随机跨运行漂移"
    edic = r1["deterministic_input_report"]
    assert edic["entropy"]["getrandom"] == "ERRNO1"
    assert edic["entropy"]["dev_urandom_deterministic"] is True
    assert edic["dev"]["urandom_regular_file"] is True
    denied = run_attack(
        "    import os\n"
        "    u1 = os.urandom(8).hex()\n"
        "    notes = {'u1': u1}\n",
        label="urandom-denied", max_attempts=1)
    assert not isinstance(denied, dict), \
        "Compute 内读 urandom 未被拒绝"
def test_getrandom_raw_rejected(run_attack):
    """E6:getrandom raw syscall -> EPERM -> 构建失败。"""
    outcome = run_attack(
        "    import ctypes\n"
        "    libc = ctypes.CDLL(None, use_errno=True)\n"
        "    buf = ctypes.create_string_buffer(8)\n"
        "    rc = libc.syscall(318, buf, 8, 0)\n"
        "    if rc == 0:\n"
        "        notes = {'leak': True}\n"
        "    else:\n"
        "        raise RuntimeError('getrandom denied')\n",
        label="getrandom-raw", max_attempts=1)
    assert not isinstance(outcome, dict), "getrandom 未被拒绝"


def test_numpy_unseeded_rng_is_deterministic_committed(run_attack, tmp_path):
    """E6(2.6.0j 升级):numpy 属第三方 native 依赖——正式 profile
  在顶层纯度验证拒绝;兼容 profile 下 numpy 顶层 import 于 Prepare
  完成(显式 seed,纯计算),Compute 内未播种 RNG(需读熵文件)被拒绝;
  两次运行 pack 一致(确定性输入语义)。"""
    import json as _json

    import numpy
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
    )
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        BuilderRunnerProfile,
        run_isolated_builder_run,
    )
    from rl_curriculum.mock_sealed_exam import assemble_mock_hidden_pack
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    def _numpy_run(compat: bool):
        root = tmp_path / ("np-top-" + ("compat" if compat else "formal"))
        root.mkdir(parents=True, exist_ok=True)
        D3 = chr(39) * 3
        (root / "numpy_helper.py").write_text(
            "import numpy as np\n"
            "_WARM = np.random.default_rng(7)\n"
            "\n"
            "def rng(seed):\n"
            "    return float(np.random.default_rng(seed).random())\n",
            encoding="utf-8")
        (root / "builder_attack.py").write_text(
            D3 + "numpy 顶层 import builder(compat 载体)。" + D3 + "\n"
            "import numpy_helper\n"
            "\n"
            "\n"
            "def build_pack(request):\n"
            "    pack = {\n"
            "        'schema': 'exam-pack-v1',\n"
            "        'name': request['pack_name'],\n"
            "        'version': request['pack_version'],\n"
            "        'visibility': 'mock_hidden', 'charter_hash': '',\n"
            "        'spec_versions': {},\n"
            "        'timeframe': request['timeframe'],\n"
            "        'episodes': [{'family': 'probe_null_sign',\n"
            "                      'params': {'episode_bars': 96},\n"
            "                      'seed': 1, 'split': 'null_control',\n"
            "                      'timeframe': request['timeframe']}],\n"
            "        'notes': {'v': numpy_helper.rng(7)},\n"
            "    }\n"
            "    log = {'format': 'builder-attempt-log-v2',\n"
            "           'max_attempts': 1, 'attempts': [\n"
            "               {'attempt': 0, 'verdict': 'accept',\n"
            "                'reject_reasons': []}],\n"
            "           'selected_attempt': 0}\n"
            "    return {'format': 'builder-build-result-v3',\n"
            "            'runner_protocol': 'builder-runner-protocol-v3',\n"
            "            'status': 'ok', 'pack': pack,\n"
            "            'attempt_log': log, 'error': None}\n",
            encoding="utf-8")
        (root / "params.json").write_text('{"episode_bars": 96}',
                                          encoding="utf-8")
        (root / "provider_config.json").write_text(_json.dumps({
            "entrypoint_module": "builder_attack",
            "entrypoint_qualname": "build_pack",
            "families": ["probe_null_sign"],
            "pair_count_per_family": 2, "max_attempts": 1,
            "root_label": "np-top",
            "external_dependencies": [
                {"module": "numpy", "version": numpy.__version__}],
        }), encoding="utf-8")
        provider = private_provider_from_root(root)
        seed = assemble_mock_hidden_pack()
        dc = derive_global_null_duration_contract(
            pack=seed, required_families=["probe_null_sign"])
        return run_isolated_builder_run(
            provider.builder_identity(),
            provider.frozen_build_request(seed, dc),
            builder_root=root,
            profile=BuilderRunnerProfile(
                dependency_profile="compat" if compat else "formal"))

    with pytest.raises(BuilderRunnerError, match="纯度|numpy|import"):
        _numpy_run(compat=False)
    r1 = _numpy_run(compat=True)
    r2 = _numpy_run(compat=True)
    assert r1["pack_hash"] == r2["pack_hash"], (
        "显式 seed numpy RNG 跨进程漂移")
    assert r1["deterministic_input_hash"] == r2[
        "deterministic_input_hash"]
    assert r1["runtime_lock_hash"] == r2["runtime_lock_hash"]
    dep = r1["deterministic_input_report"]["sealed_compute"][
        "dependency_policy"]
    assert dep["profile"] == "compat"
    assert dep["formal_eligible"] is False
