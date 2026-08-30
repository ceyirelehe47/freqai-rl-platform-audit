"""工作包 A1/G8:模块顶层纯度矩阵(资格阶段拒绝)。

顶层 import 时执行 time/random/stat/sysinfo/getcpu/ctypes/thread 的
builder 在 EntryPoint 被采信前拒绝(AST 静态 + toplevel 运行时审计
双防线;AST 是第一道——顶层只允许 allowlist import/def/class/字面量
赋值/docstring)。
"""

from __future__ import annotations

import json
from pathlib import Path

from rl_builder_runtime.sealed_compute import (
    validate_top_level_purity,
)


def _toplevel_builder(root: Path, top_stmts: str) -> Path:
    src = (
        "'''顶层副作用攻击 builder。'''\n"
        f"{top_stmts}"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    pack = {\n"
        "        'schema': 'exam-pack-v1', 'name': request['pack_name'],\n"
        "        'version': request['pack_version'],\n"
        "        'visibility': 'mock_hidden', 'charter_hash': '',\n"
        "        'spec_versions': {}, 'timeframe': request['timeframe'],\n"
        "        'episodes': [{'family': 'probe_null_sign',\n"
        "                      'params': {'episode_bars': 96}, 'seed': 1,\n"
        "                      'split': 'null_control',\n"
        "                      'timeframe': request['timeframe']}],\n"
        "        'notes': {},\n"
        "    }\n"
        "    log = {'format': 'builder-attempt-log-v2',\n"
        "           'max_attempts': 1, 'attempts': [\n"
        "               {'attempt': 0, 'verdict': 'accept',\n"
        "                'reject_reasons': []}],\n"
        "           'selected_attempt': 0}\n"
        "    return {'format': 'builder-build-result-v3',\n"
        "            'runner_protocol': 'builder-runner-protocol-v3',\n"
        "            'status': 'ok', 'pack': pack,\n"
        "            'attempt_log': log, 'error': None}\n"
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "builder_attack.py").write_text(src, encoding="utf-8")
    (root / "params.json").write_text('{"episode_bars": 96}',
                                      encoding="utf-8")
    (root / "provider_config.json").write_text(json.dumps({
        "entrypoint_module": "builder_attack",
        "entrypoint_qualname": "build_pack",
        "families": ["probe_null_sign"], "pair_count_per_family": 2,
        "max_attempts": 1, "root_label": "toplevel-attack",
    }), encoding="utf-8")
    return root


def _run_formal(root: Path, seed_pack_and_dc):
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        BuilderRunnerProfile,
        run_isolated_builder_run,
    )
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
    )

    provider = private_provider_from_root(root)
    seed, dc = seed_pack_and_dc
    return run_isolated_builder_run(
        provider.builder_identity(),
        provider.frozen_build_request(seed, dc),
        builder_root=root, profile=BuilderRunnerProfile())


G8_CASES = {
    "time": "import time\nT = time.time()\n",
    "random": "import random\nR = random.random()\n",
    "os_stat": "import os\nINO = os.stat('/manifest.json').st_ino\n",
    "sysinfo": "import ctypes\nU = ctypes.CDLL(None).sysinfo(0)\n",
    "getcpu": ("import ctypes\n"
               "C = ctypes.CDLL(None).sched_getcpu()\n"),
    "ctypes_open": "import ctypes\nL = ctypes.CDLL(None)\n",
    "thread": ("import threading\n"
               "E = threading.Event()\n"
               "T = threading.Thread(target=lambda: None)\n"),
    "open_file": "DATA = open('/manifest.json', 'rb').read(4)\n",
    "call_in_toplevel": "V = __import__('os').getpid()\n",
    "comprehension_call": "XS = [abs(i) for i in range(3)]\n",
}


def test_ast_rejects_all_g8_top_levels():
    """AST 静态层:全部 G8 顶层形态被拒。"""
    for name, stmts in G8_CASES.items():
        report = validate_top_level_purity(stmts, "m")
        assert not report["ok"], f"{name} 顶层未被 AST 拒绝"


def test_real_chain_rejects_toplevel_side_effects(tmp_path,
                                                  seed_pack_and_dc):
    """真实链路:顶层副作用 builder 在资格阶段 fail closed。"""
    from rl_curriculum.builder_runner import BuilderRunnerError
    import pytest

    for name, stmts in G8_CASES.items():
        root = _toplevel_builder(tmp_path / f"g8-{name}", stmts)
        with pytest.raises(BuilderRunnerError, match="纯度|违规|import"):
            _run_formal(root, seed_pack_and_dc)


def test_toplevel_literal_constants_accepted(tmp_path, seed_pack_and_dc):
    """合法顶层(字面量常量 + def)真实链路通过。"""
    root = _toplevel_builder(
        tmp_path / "g8-ok",
        "import math\n"
        "K = {'a': 1, 'b': (2.0, 3.0)}\n"
        "N = 42\n")
    run = _run_formal(root, seed_pack_and_dc)
    assert run["status"] == "ok"
    purity = run["runtime_lock"]["sealed_compute"]["top_level_purity"]
    assert purity["all_ok"] is True
    assert purity["digest"].startswith("pur-")


def test_class_body_restricted():
    """类体同顶层规则(类体在 import 时执行)。"""
    bad = (
        "import math\n"
        "class C:\n"
        "    X = math.sqrt(2)\n"          # 类体调用 -> 拒绝
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    return None\n"
    )
    report = validate_top_level_purity(bad, "m")
    assert not report["ok"]
    good = (
        "class C:\n"
        "    X = 1\n"
        "\n"
        "    def m(self):\n"
        "        return 2\n"
    )
    report = validate_top_level_purity(good, "m")
    assert report["ok"], report["problems"]
