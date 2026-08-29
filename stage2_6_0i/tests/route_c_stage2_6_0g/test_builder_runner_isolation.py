"""阶段 2.6.0g 收尾:工作包 B/C3/H 攻击矩阵——隔离 Runner。

- TOCTOU:identity 哈希后修改源文件/staging 复制后替换文件/新增
  helper/删除资源文件 -> 启动前对账拒绝;
- 源码 A / 执行 B:staging 与 identity 不一致拒绝;
- 主进程模块缓存污染:隔离进程内无缓存可污染;
- Candidate 不可见:argv/env/请求/cwd 不含 checkpoint 路径;
- inspect.stack 攻击:Runner 内调用栈无外部 pack;
- sys.argv/env/文件系统搜索 checkpoint:攻击 builder 拿不到且被拒。
"""

from __future__ import annotations

import json
import sys

import pytest

from tests.route_c_stage2_6_0f.conftest import (
    PRIVATE_BUILDER_A_FILES,
    private_provider_from_root,
    write_private_builder,
)


def _private_request(provider, pack, dc):
    return provider.frozen_build_request(pack, dc)


def test_identity_hash_then_modify_source_rejected(tmp_path, sealed_exam_env,
                                                   duration_contract,
                                                   mock_pack):
    """identity 派生后修改源文件 -> staging 对账失败(fail closed)。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        run_isolated_builder_run,
    )

    root = write_private_builder(tmp_path / "toctou_modify")
    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    # identity 哈希后修改源文件
    (root / "helpers.py").write_text(
        (root / "helpers.py").read_text() + "\n# tampered\n",
        encoding="utf-8")
    with pytest.raises(BuilderRunnerError, match="TOCTOU|不一致"):
        run_isolated_builder_run(
            identity, req, builder_root=root,
            staging_base=tmp_path / "staging1")


def test_staging_replaced_after_copy_rejected(
        tmp_path, monkeypatch, sealed_exam_env, duration_contract,
        mock_pack):
    """staging 复制后、启动前替换文件 -> 对账拒绝(monkeypatch 注入)。"""
    from rl_curriculum import builder_runner as bn
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        run_isolated_builder_run,
    )

    root = write_private_builder(tmp_path / "toctou_replace")
    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    original = bn.assemble_builder_staging

    def sabotage(builder_root, base_dir):
        staging = original(builder_root, base_dir)
        # 复制完成后追加字节(TOCTOU 窗口内篡改)
        target = staging / "helpers.py"
        target.write_text(target.read_text() + "\n# replaced\n")
        return staging

    monkeypatch.setattr(bn, "assemble_builder_staging", sabotage)
    with pytest.raises(BuilderRunnerError, match="TOCTOU|不一致"):
        run_isolated_builder_run(
            identity, req, builder_root=root,
            staging_base=tmp_path / "staging2")


def test_staging_file_removed_rejected(tmp_path, monkeypatch,
                                       sealed_exam_env, duration_contract,
                                       mock_pack):
    from rl_curriculum import builder_runner as bn
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        run_isolated_builder_run,
    )

    root = write_private_builder(tmp_path / "toctou_remove")
    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    original = bn.assemble_builder_staging

    def sabotage(builder_root, base_dir):
        staging = original(builder_root, base_dir)
        (staging / "pack_selection.py").unlink()
        return staging

    monkeypatch.setattr(bn, "assemble_builder_staging", sabotage)
    with pytest.raises(BuilderRunnerError, match="TOCTOU|不一致"):
        run_isolated_builder_run(
            identity, req, builder_root=root,
            staging_base=tmp_path / "staging3")


def test_new_helper_after_identity_rejected(tmp_path, sealed_exam_env,
                                            duration_contract, mock_pack):
    """identity 后新增 helper 文件 -> staging 多出文件,对账拒绝。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        run_isolated_builder_run,
    )

    root = write_private_builder(tmp_path / "toctou_new")
    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    (root / "sneaky_helper.py").write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(BuilderRunnerError, match="TOCTOU|额外文件"):
        run_isolated_builder_run(
            identity, req, builder_root=root,
            staging_base=tmp_path / "staging4")


def test_source_a_execution_b_rejected(tmp_path, sealed_exam_env,
                                       duration_contract, mock_pack):
    """identity 绑定 A 的内容,实际执行 B(root 内容已变) -> 拒绝。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        run_isolated_builder_run,
    )

    root = write_private_builder(tmp_path / "src_a_exec_b")
    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    # 换成"执行 B":重写 entrypoint 的行为
    files = dict(PRIVATE_BUILDER_A_FILES)
    (root / "builder_a.py").write_text(
        files["builder_a.py"].replace(
            "'namespace': 'pack-construction-v1'",
            "'namespace': 'pack-construction-v2'"),
        encoding="utf-8")
    with pytest.raises(BuilderRunnerError, match="TOCTOU|内容变化"):
        run_isolated_builder_run(
            identity, req, builder_root=root,
            staging_base=tmp_path / "staging5")


def test_runner_argv_env_request_no_candidate_material(
        tmp_path, sealed_exam_env, duration_contract, mock_pack,
        monkeypatch):
    """B4:Runner 的 argv/env/请求/cwd 不得包含任何候选材料。

    monkeypatch launch_builder_runner 捕获全部入参(含传给子进程的
    config JSON)逐项断言;launch 后立即失败即可(参数已捕获)。
    """
    captured = {}

    def fake_launch(profile, *, bundle_entry, entrypoint_module,
                    entrypoint_qualname, worker_info_fd=None):
        captured["launch"] = {
            "bundle_staging": str(bundle_entry["staging"]),
            "bundle_digest": str(bundle_entry["digest"]),
            "module": entrypoint_module,
            "qualname": entrypoint_qualname,
            "worker_info_fd": worker_info_fd,
            "rlimits": dict(profile.rlimits),
            "env_whitelist": sorted(profile.canonical_payload()[
                "env_whitelist"]),
        }

        class _Boom(RuntimeError):
            pass

        raise _Boom("captured-before-spawn")

    from rl_curriculum import builder_runner as bn

    monkeypatch.setattr(bn, "launch_builder_runner", fake_launch)
    root = write_private_builder(tmp_path / "argv_audit")
    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    with pytest.raises((bn.BuilderRunnerError, RuntimeError)):
        bn.run_isolated_builder_run(
            identity, req, builder_root=root,
            staging_base=tmp_path / "staging6")
    blob = json.dumps(captured) + json.dumps(req)
    for forbidden in ("checkpoint", "sidecar", ".rl_manifest",
                      ".rl_attestation", "attestation"):
        assert forbidden not in blob, f"Runner 输入暴露 {forbidden}"


def test_inspect_stack_attack_builder_cannot_get_pack(
        tmp_path, sealed_exam_env, duration_contract, mock_pack):
    """H 主动攻击 1:builder 通过 inspect.stack() 搜索调用方局部变量
    pack——隔离 Runner 的调用方局部只有 request,无外部 pack,攻击
    builder 拿不到材料且构建失败。"""
    files = dict(PRIVATE_BUILDER_A_FILES)
    files["builder_a.py"] = (
        "'''攻击 builder:inspect.stack 搜 caller pack。'''\n"
        "import inspect\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    found = None\n"
        "    for frame_info in inspect.stack():\n"
        "        for var_name, value in frame_info.frame.f_locals.items():\n"
        "            if var_name == 'pack' and value is not None:\n"
        "                found = ('stack', var_name)\n"
        "    if found is not None:\n"
        "        return {'format': 'builder-build-result-v3',\n"
        "                'runner_protocol': 'builder-runner-protocol-v3',\n"
        "                'status': 'failed', 'pack': None,\n"
        "                'attempt_log': {'format':\n"
        "                                'builder-attempt-log-v2',\n"
        "                                'max_attempts': 0, 'attempts': [],\n"
        "                                'selected_attempt': None},\n"
        "                'error': 'stack-attack-succeeded'}\n"
        "    return {'format': 'builder-build-result-v3',\n"
        "            'runner_protocol': 'builder-runner-protocol-v3',\n"
        "            'status': 'failed', 'pack': None,\n"
        "            'attempt_log': {'format': 'builder-attempt-log-v2',\n"
        "                            'max_attempts': 0, 'attempts': [],\n"
        "                            'selected_attempt': None},\n"
        "            'error': 'stack-attack-no-pack-found'}\n"
    )
    root = write_private_builder(
        tmp_path / "stack_attack", files, label="stack-attacker")
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        run_isolated_builder_run,
    )

    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    with pytest.raises(BuilderRunnerError,
                       match="stack-attack-no-pack-found|构建失败"):
        run_isolated_builder_run(
            identity, req, builder_root=root,
            staging_base=tmp_path / "staging7")


def test_env_argv_scan_attack_builder_rejected(
        tmp_path, sealed_exam_env, duration_contract, mock_pack):
    """H 主动攻击 2:builder 扫 sys.argv/os.environ/文件系统搜
    checkpoint——Runner 内拿不到材料且构建失败。"""
    files = dict(PRIVATE_BUILDER_A_FILES)
    files["builder_a.py"] = (
        "'''攻击 builder:argv/env/文件系统扫描。'''\n"
        "import os\n"
        "import sys\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    hits = []\n"
        "    for a in sys.argv:\n"
        "        if 'checkpoint' in a or 'manifest' in a:\n"
        "            hits.append(('argv', a))\n"
        "    for k, v in os.environ.items():\n"
        "        if 'checkpoint' in k.lower() or 'candidate' in k.lower() \\\n"
        "                or 'checkpoint' in v:\n"
        "            hits.append(('env', k))\n"
        "    for name in os.listdir('.'):\n"
        "        if 'checkpoint' in name or 'manifest' in name:\n"
        "            hits.append(('cwd', name))\n"
        "    if hits:\n"
        "        err = 'scan-attack-succeeded:' + repr(hits[:2])\n"
        "    else:\n"
        "        err = 'scan-attack-nothing-found'\n"
        "    return {'format': 'builder-build-result-v3',\n"
        "            'runner_protocol': 'builder-runner-protocol-v3',\n"
        "            'status': 'failed', 'pack': None,\n"
        "            'attempt_log': {'format': 'builder-attempt-log-v2',\n"
        "                            'max_attempts': 0, 'attempts': [],\n"
        "                            'selected_attempt': None},\n"
        "            'error': err}\n"
    )
    root = write_private_builder(
        tmp_path / "scan_attack", files, label="scan-attacker")
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        run_isolated_builder_run,
    )

    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    with pytest.raises(BuilderRunnerError,
                       match="scan-attack-nothing-found|构建失败"):
        run_isolated_builder_run(
            identity, req, builder_root=root,
            staging_base=tmp_path / "staging8")


def test_checkpoint_sentinel_never_opened(tmp_path, sealed_exam_env,
                                          duration_contract, mock_pack):
    """H:哨兵文件断言——builder 阶段 checkpoint 从未被 Runner open。

    在评估工作区放哨兵 checkpoint 文件;Runner 的 Landlock 不授予
    该目录,builder 即使尝试读取也会失败;access 审计应为空。"""
    sentinel_dir = tmp_path / "eval_workspace"
    sentinel_dir.mkdir()
    sentinel = sentinel_dir / "model.zip"
    sentinel.write_bytes(b"SENTINEL-CHECKPOINT")
    from rl_curriculum.builder_runner import (
        run_isolated_builder_run,
    )

    root = write_private_builder(tmp_path / "sentinel_builder")
    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    run = run_isolated_builder_run(
        identity, req, builder_root=root,
        staging_base=tmp_path / "staging9")
    assert run["access_summary"]["outside_allowlist"] == []
    # 哨兵未被触碰
    assert sentinel.read_bytes() == b"SENTINEL-CHECKPOINT"


def test_deterministic_double_run(tmp_path, sealed_exam_env,
                                  duration_contract, mock_pack):
    """确定性:两次全新隔离运行三组 hash 完全一致(不含系统时间/
    未冻结随机种子影响)。"""
    from rl_curriculum.builder_runner import (
        run_isolated_builder_run,
    )

    root = write_private_builder(tmp_path / "determinism")
    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    req = _private_request(provider, mock_pack, duration_contract)
    r1 = run_isolated_builder_run(
        identity, req, builder_root=root,
        staging_base=tmp_path / "staging10a")
    r2 = run_isolated_builder_run(
        identity, req, builder_root=root,
        staging_base=tmp_path / "staging10b")
    assert r1["pack_hash"] == r2["pack_hash"]
    assert r1["attempt_log_hash"] == r2["attempt_log_hash"]
    assert r1["runtime_lock_hash"] == r2["runtime_lock_hash"]
