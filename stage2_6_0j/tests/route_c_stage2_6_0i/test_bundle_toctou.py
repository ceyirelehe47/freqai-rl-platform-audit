"""工作包 E10:bundle TOCTOU 攻击矩阵(真实生产路径)。

- manifest 后修改 staging 文件内容 -> 下次 Worker 挂载视图全量复验
  拒绝(启动失败,无 pack);
- precommit 与 replay 之间修改 bundle -> 重放对账拒绝;
- 硬链接别名:组装后修改**源 conda env 文件**(就地写)-> staging
  同 inode 变化 -> 运行后复验拒绝;
- bundle 结构新增文件 -> 拒绝;
- bundle digest 被篡改(EDIC/runtime_bundle) -> 不变量校验拒绝。
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.stage2_6_0i


def test_staging_tamper_between_runs_rejected(run_attack, tmp_path):
    """组装成功一次后篡改 staging 文件 -> 第二次运行(挂载视图复验)
  启动失败。"""
    body = "    pass\n"
    r1 = run_attack(body, label="toctou-a", max_attempts=1)
    assert isinstance(r1, dict), r1
    # 定位共享池中该链路的 staging 并篡改一个 builder 包文件
    from rl_curriculum.builder_runner import shared_bundle_pool

    pool = shared_bundle_pool()
    entries = [v for v in pool._cache.values()]  # noqa: SLF001
    assert entries
    staging = entries[-1]["staging"]
    target = staging / "builder_pkg" / "builder_attack.py"
    assert target.is_file()
    target.write_text(target.read_text() + "# tampered\n")
    outcome = run_attack(body, label="toctou-a", max_attempts=1)
    assert not isinstance(outcome, dict), "篡改后的 bundle 仍被采信"
    name, msg = outcome
    assert name in ("BuilderRunnerError", "BuilderProvenanceError"), outcome
    # 恢复现场,避免污染共享池其他用例
    target.write_text(target.read_text().replace("# tampered\n", ""))
    pool.verify_staging(entries[-1])  # 恢复后可复验通过


def test_hardlink_alias_inplace_write_detected(run_attack, tmp_path):
    """E10 核心:组装后对**源 conda env 文件**就地写入(硬链接别名)
  -> staging 同 inode 内容变化 -> 运行后复验拒绝(TOCTOU 在输出
  采信路径被发现)。"""
    import hashlib

    body = "    notes = {'h': hashlib.sha256(b'x').hexdigest()}\n"
    r1 = run_attack(body, label="toctou-alias", max_attempts=1,
                    top_imports="import hashlib\n")
    assert isinstance(r1, dict), r1
    from rl_curriculum.builder_runner import shared_bundle_pool

    pool = shared_bundle_pool()
    entry = [v for v in pool._cache.values()][-1]  # noqa: SLF001
    staging = entry["staging"]
    # 选一个 env 内小文件(组装自硬链接),就地改写源
    victim_src = None
    victim_staged = None
    for e in entry["manifest"]["entries"]:
        if e.get("type") == "file" and e["path"].startswith(
                "lib/python3.11/") and 0 < e["size"] < 4000 \
                and e["path"].endswith(".py"):
            staged = staging / e["path"]
            # 找出源 env 中同 inode 的文件(硬链接别名)
            import os

            st_staged = staged.stat()
            env_root = None
            import sys as _sys
            from pathlib import Path as _P

            env_root = _P(_sys.executable).parent.parent / \
                "lib/python3.11"
            src = env_root / e["path"][len("lib/python3.11/"):]
            if src.is_file() and src.stat().st_ino == st_staged.st_ino:
                victim_src, victim_staged = src, staged
                break
    assert victim_src is not None, "未找到硬链接别名样本"
    original = victim_src.read_bytes()
    try:
        victim_src.write_bytes(original + b"# alias-tamper\n")
        from rl_builder_runtime.bundle import BundleError

        with pytest.raises(BundleError):
            pool.verify_staging(entry)
    finally:
        victim_src.write_bytes(original)
    pool.verify_staging(entry)  # 恢复后复验通过


def test_bundle_digest_tamper_in_evidence_rejected(run_attack):
    """EDIC/runtime_bundle 摘要被篡改 -> 不变量校验拒绝(即使重算
  edi 哈希也不与承诺一致)。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerError, BuilderRunnerProfile,
        check_effective_deterministic_input_report,
    )

    run = run_attack("    pass\n", label="toctou-digest", max_attempts=1)
    assert isinstance(run, dict), run
    edic = json.loads(json.dumps(run["deterministic_input_report"]))
    edic["runtime_bundle"]["manifest_digest"] = "rbm-" + "0" * 64
    with pytest.raises(BuilderRunnerError, match="bundle 摘要|不一致"):
        check_effective_deterministic_input_report(
            edic, BuilderRunnerProfile(),
            bundle_digest=run["runtime_bundle_hash"])


def test_thread_state_tamper_rejected(run_attack):
    """EDIC supervisor.thread_count 篡改 -> 校验拒绝。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerError, BuilderRunnerProfile,
        check_effective_deterministic_input_report,
    )

    run = run_attack("    pass\n", label="toctou-thread", max_attempts=1)
    assert isinstance(run, dict), run
    edic = json.loads(json.dumps(run["deterministic_input_report"]))
    edic["supervisor"]["thread_count"] = 2
    with pytest.raises(BuilderRunnerError, match="线程静止"):
        check_effective_deterministic_input_report(
            edic, BuilderRunnerProfile(),
            bundle_digest=run["runtime_bundle_hash"])


def test_seccomp_policy_tamper_rejected(run_attack):
    """EDIC seccomp 策略载荷篡改 -> filter 摘要/策略校验拒绝。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerError, BuilderRunnerProfile,
        check_effective_deterministic_input_report,
    )

    run = run_attack("    pass\n", label="toctou-seccomp", max_attempts=1)
    assert isinstance(run, dict), run
    edic = json.loads(json.dumps(run["deterministic_input_report"]))
    edic["seccomp"]["policy"] = dict(edic["seccomp"]["policy"],
                                     thread_policy="allowed")
    with pytest.raises(BuilderRunnerError):
        check_effective_deterministic_input_report(
            edic, BuilderRunnerProfile(),
            bundle_digest=run["runtime_bundle_hash"])
