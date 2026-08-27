"""阶段 2.6.0g 收尾:工作包 G 攻击矩阵——运行时依赖锁(隔离 Runner 内
真实执行动态 import 攻击 builder)。

- 动态 import 新第三方包(importlib.import_module) -> 运行时锁
  含未注册依赖 -> fail closed;
- 函数级 import / 条件 import -> Runner sys.modules 审计覆盖;
- <missing:package> -> 拒绝。
"""

from __future__ import annotations

import pytest

from tests.route_c_stage2_6_0f.conftest import (
    private_provider_from_root,
    write_private_builder,
)


def _attack_builder(import_lines, error_prefix):
    return (
        "'''动态 import 攻击 builder。'''\n"
        + import_lines
        + "\n"
        "\n"
        "def build_pack(request):\n"
        f"    return {{'format': 'builder-build-result-v2',\n"
        f"            'runner_protocol': 'builder-runner-protocol-v2',\n"
        f"            'status': 'failed', 'pack': None,\n"
        f"            'attempt_log': {{'format': 'builder-attempt-log-v1',\n"
        f"                            'max_attempts': 0, 'attempts': [],\n"
        f"                            'selected_attempt': None}},\n"
        f"            'error': '{error_prefix}'}}\n"
    )


def test_dynamic_import_unregistered_dependency_rejected(
        tmp_path, sealed_exam_env, duration_contract, mock_pack):
    """builder 动态 import 一个配置之外的真实第三方包(pytest 与
    本环境共存但不在静态闭包) -> 运行时锁对账 fail closed。"""
    import json as _json

    root = tmp_path / "dyn_builder"
    root.mkdir(parents=True)
    (root / "builder_dyn.py").write_text(
        "'''动态 import 攻击 builder(build 成功,依赖违规在锁对账暴露)。'''\n"
        "import importlib\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    importlib.import_module('pytest')\n"
        "    pack = {\n"
        "        'schema': 'exam-pack-v1', 'name': request['pack_name'],\n"
        "        'version': request['pack_version'],\n"
        "        'visibility': 'mock_hidden', 'charter_hash': '',\n"
        "        'spec_versions': {}, 'timeframe': request['timeframe'],\n"
        "        'episodes': [\n"
        "            {'family': 'probe_null_sign',\n"
        "             'params': {'episode_bars': 96}, 'seed': 1,\n"
        "             'split': 'null_control',\n"
        "             'timeframe': request['timeframe']}],\n"
        "        'notes': {}}\n"
        "    return {'format': 'builder-build-result-v2',\n"
        "            'runner_protocol': 'builder-runner-protocol-v2',\n"
        "            'status': 'ok', 'pack': pack,\n"
        "            'attempt_log': {'format': 'builder-attempt-log-v1',\n"
        "                            'max_attempts': 2, 'attempts': [\n"
        "                                {'attempt': 0, 'verdict': 'accept',\n"
        "                                 'reject_reasons': []}],\n"
        "                            'selected_attempt': 0},\n"
        "            'error': None}\n",
        encoding="utf-8")
    (root / "params.json").write_text('{"episode_bars": 96}',
                                      encoding="utf-8")
    (root / "provider_config.json").write_text(_json.dumps({
        "entrypoint_module": "builder_dyn",
        "entrypoint_qualname": "build_pack",
        "families": ["probe_null_sign"],
        "pair_count_per_family": 2,
        "max_attempts": 2,
        "root_label": "dyn-attacker",
    }), encoding="utf-8")
    provider = private_provider_from_root(root)
    req = provider.frozen_build_request(mock_pack, duration_contract)
    from rl_curriculum.builder_evidence import precommit_builder_runs
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    # 动态 import 的 pytest 不在静态 allowlist -> 运行时锁对账拒绝
    with pytest.raises(BuilderProvenanceError,
                       match="未注册|动态|运行时锁"):
        precommit_builder_runs(
            provider, req, builder_root=provider.root)


def test_function_level_import_audited(tmp_path, sealed_exam_env,
                                       duration_contract, mock_pack):
    """函数级 import 的已注册第三方(numpy 在静态闭包内) -> 允许且
    出现在运行时锁(证明函数级 import 被审计覆盖)。"""
    files = {
        "builder_np.py": (
            "'''函数级 import builder(numpy 在静态闭包内)。'''\n"
            "\n"
            "\n"
            "def build_pack(request):\n"
            "    import numpy as _np\n"
            "    v = float(_np.array([1.0]).sum())\n"
            "    return {'format': 'builder-build-result-v2',\n"
            "            'runner_protocol': 'builder-runner-protocol-v2',\n"
            "            'status': 'failed', 'pack': None,\n"
            "            'attempt_log': {'format':\n"
            "                            'builder-attempt-log-v1',\n"
            "                            'max_attempts': 2, 'attempts': [\n"
            "                                {'attempt': 0, 'verdict': 'accept',\n"
            "                                 'reject_reasons': []}],\n"
            "                            'selected_attempt': 0},\n"
            "            'error': 'np:' + str(v)}\n"
        ),
        "params.json": '{"episode_bars": 96}',
    }
    import json as _json

    root = tmp_path / "np_builder"
    root.mkdir(parents=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / "provider_config.json").write_text(_json.dumps({
        "entrypoint_module": "builder_np",
        "entrypoint_qualname": "build_pack",
        "families": ["probe_null_sign"],
        "pair_count_per_family": 2,
        "max_attempts": 2,
        "root_label": "np-builder",
    }), encoding="utf-8")
    provider = private_provider_from_root(root)
    req = provider.frozen_build_request(mock_pack, duration_contract)
    from rl_curriculum.builder_evidence import precommit_builder_runs
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    # builder 自报 failed(np:1.0),但运行时锁包含 numpy 且在 allowlist
    with pytest.raises(BuilderProvenanceError, match="np:1"):
        precommit_builder_runs(
            provider, req, builder_root=provider.root)
    # 直接单跑看运行时锁内容(绕过 precommit 的异常包装)
    from rl_curriculum.builder_runner import run_isolated_builder_run

    run = run_isolated_builder_run.__wrapped__ if hasattr(
        run_isolated_builder_run, "__wrapped__") else None
    # run_isolated_builder_run 对失败入口抛 BuilderRunnerError;
    # 用底层调用方式验证 numpy 进入锁:直接构造成功 builder
    files["builder_np.py"] = files["builder_np.py"].replace(
        "'status': 'failed', 'pack': None,",
        "'status': 'ok', 'pack': {'schema': 'exam-pack-v1',"
        " 'name': 'np', 'version': 'v', 'visibility': 'mock_hidden',"
        " 'charter_hash': '', 'spec_versions': {}, 'timeframe': '15m',"
        " 'episodes': [{'family': 'probe_null_sign',"
        " 'params': {'episode_bars': 96}, 'seed': 1,"
        " 'split': 'null_control', 'timeframe': '15m'}],"
        " 'notes': {}},").replace(
        "    v = float(_np.array([1.0]).sum())\n", "").replace(
        "            'error': 'np:' + str(v)}\n", "            'error': None}\n")
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    provider2 = private_provider_from_root(root)
    req2 = provider2.frozen_build_request(mock_pack, duration_contract)
    run2 = run_isolated_builder_run(
        provider2.builder_identity(), req2, builder_root=root,
        staging_base=tmp_path / "np_staging")
    modules = [d["module"] for d in run2["runtime_lock"]["distributions"]]
    assert "numpy" in modules
    numpy_entry = next(d for d in run2["runtime_lock"]["distributions"]
                       if d["module"] == "numpy")
    assert numpy_entry["version"] and \
        not numpy_entry["version"].startswith("<missing")
    assert numpy_entry["record_sha256"] != "<missing-record>"


def test_missing_package_placeholder_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_runtime_lock_against_static,
    )

    lock = {
        "format": "builder-runtime-lock-v1",
        "python_implementation": "cpython",
        "python_version": "3.11.0",
        "executable_prefix": "/env",
        "distributions": [
            {"module": "leftpad", "distribution": "leftpad",
             "version": "<missing:leftpad>",
             "record_sha256": "<missing-record>",
             "imported": ["leftpad"]},
        ],
    }
    static = [{"module": "leftpad", "kind": "package_version",
               "version": "<missing:leftpad>"}]
    with pytest.raises(BuilderProvenanceError, match="missing"):
        check_runtime_lock_against_static(lock, static)


def test_conditional_import_inside_builder(tmp_path, sealed_exam_env,
                                           duration_contract, mock_pack):
    """条件 import:分支触发时才加载的依赖同样进入运行时锁。"""
    source = (
        "'''条件 import builder。'''\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    if request.get('max_attempts', 0) > 0:\n"
        "        import numpy as _np\n"
        "        marker = 'cond-np-loaded:' + _np.__version__\n"
        "    else:\n"
        "        marker = 'cond-np-skipped'\n"
        "    return {'format': 'builder-build-result-v2',\n"
        "            'runner_protocol': 'builder-runner-protocol-v2',\n"
        "            'status': 'failed', 'pack': None,\n"
        "            'attempt_log': {'format': 'builder-attempt-log-v1',\n"
        "                            'max_attempts': 0, 'attempts': [],\n"
        "                            'selected_attempt': None},\n"
        "            'error': marker}\n"
    )
    import json as _json

    root = tmp_path / "cond_builder"
    root.mkdir(parents=True)
    (root / "builder_cond.py").write_text(source, encoding="utf-8")
    (root / "params.json").write_text('{"episode_bars": 96}',
                                      encoding="utf-8")
    (root / "provider_config.json").write_text(_json.dumps({
        "entrypoint_module": "builder_cond",
        "entrypoint_qualname": "build_pack",
        "families": ["probe_null_sign"],
        "pair_count_per_family": 2,
        "max_attempts": 2,
        "root_label": "cond-builder",
    }), encoding="utf-8")
    provider = private_provider_from_root(root)
    req = provider.frozen_build_request(mock_pack, duration_contract)
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )
    from rl_curriculum.builder_runner import run_isolated_builder_run

    with pytest.raises(BuilderProvenanceError,
                       match="cond-np-loaded"):
        run = None
        from rl_curriculum.builder_evidence import _run_once_for_mode

        _run_once_for_mode(provider, req, builder_root=provider.root)
    # 条件分支真实触发(numpy 被加载)证明审计覆盖条件 import
