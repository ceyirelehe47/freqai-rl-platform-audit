# -*- coding: utf-8 -*-
"""R14 测试:真实 artifact round-trip(§四-1/§四-3)。

覆盖:
- canonical accessor read_preprocessor_bundle_hash 的全 fail-closed
  语义,输入使用正式 producer(RouteCPreprocessorV2.identity())真实
  生成的 payload(非手工构造 dict);
- 正/负路径在独立子进程读取(不依赖测试进程内存状态);
- 旧键名 'bundle_hash' 不得冒充 canonical 字段(R12 缺陷的回归锁);
- CLI 独立进程测试(namespace-integrity rc=0;audit 缺 freeze rc=1
  fail closed);
- design plan payload 的 rehearsal 覆盖参数与显式 semantic 映射;
- exposure marker 一次性语义(隔离目录)。

完整 production command → 落盘 → 独立 CLI 进程读取 → 下游命令成功
的端到端链由 R14RealArtifactCliRoundTrip-v1(cmd_real_artifact_
rehearsal,subprocess 全链)在 pre-freeze 阶段执行,其证据 artifact
为 real_artifact_cli_roundtrip.json;本文件覆盖单元级语义锁。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _engineering_pack() -> dict:
    from rl_curriculum.curriculum261_r14_param_pack import (
        ladder_pack_payload_r14,
        pack_digest_r14,
        r14_candidate_grid,
    )

    ladder = r14_candidate_grid()["c2l_historical_control"]
    pack = ladder_pack_payload_r14(
        selected_c2_candidate="c2l_historical_control",
        c2_ladder=ladder,
        selected_block_count=10,
        design_plan_digest="r14dp-test-engineering",
        matched_contract_identity="test-engineering",
        block_integrity_identity="test-engineering",
        cue_semantic_contract_digest="r14cue-test",
        cue_semantic_rule_identity="test-engineering",
        cue_audit_digest="r14ca-test",
        p_contract=0.9504,
        recall_floor_value=0.9304,
        noninferiority_delta=0.02,
        semantic_blocks_per_corpus=160,
        baseline_commit="test",
    )
    pack["digest"] = pack_digest_r14(pack)
    return pack


def _tiny_real_v2():
    """正式 producer 路径的最小真实 V2(preplan 工程 namespace)。"""
    from rl_curriculum.curriculum261_r14_calibration import (
        fit_preprocessor_v2_from_bank_r14,
        generate_fit_bank_r14,
    )

    pack = _engineering_pack()
    records = generate_fit_bank_r14("preplan_fit_main_r14", pack)
    v2, _manifest = fit_preprocessor_v2_from_bank_r14(
        "preplan_fit_main_r14", pack, records=records,
        parameter_pack_identity=pack["digest"])
    return v2


@pytest.fixture(scope="module")
def real_identity(tmp_path_factory):
    """正式 producer 真实生成的 identity payload + 其落盘文件。"""
    v2 = _tiny_real_v2()
    identity = v2.identity()
    out_dir = tmp_path_factory.mktemp("r14_bundle")
    path = out_dir / "preprocessor_bundle_calibration.json"
    path.write_text(json.dumps(identity, indent=1, default=str),
                    encoding="utf-8")
    return v2, identity, path


class TestReadPreprocessorBundleHash:
    def test_canonical_field_read_from_real_producer_output(
            self, real_identity):
        from rl_curriculum.curriculum261_r14_plan import (
            PREPROCESSOR_BUNDLE_IDENTITY_FIELD,
            read_preprocessor_bundle_hash,
        )

        v2, identity, path = real_identity
        value = read_preprocessor_bundle_hash(
            path, consumer_command="test")
        assert value.startswith("r4pb-")
        assert value == identity[
            PREPROCESSOR_BUNDLE_IDENTITY_FIELD]
        assert value == v2.bundle_hash

    def test_identity_payload_has_no_legacy_key(self, real_identity):
        """producer 输出不含旧键 'bundle_hash'(合同漂移锁)。"""
        _, identity, _ = real_identity
        assert "preprocessor_bundle_hash" in identity
        assert "bundle_hash" not in identity

    def test_missing_artifact_fail_closed(self, tmp_path):
        from rl_curriculum.curriculum261_r14_plan import (
            read_preprocessor_bundle_hash,
        )

        missing = tmp_path / "preprocessor_bundle_calibration.json"
        with pytest.raises(RuntimeError, match="缺失"):
            read_preprocessor_bundle_hash(
                missing, consumer_command="r14-cli lock-plan")

    def test_missing_canonical_field_fail_closed(self, real_identity,
                                                 tmp_path):
        from rl_curriculum.curriculum261_r14_plan import (
            read_preprocessor_bundle_hash,
        )

        _, identity, _ = real_identity
        tampered = dict(identity)
        tampered.pop("preprocessor_bundle_hash")
        path = tmp_path / "preprocessor_bundle_calibration.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        with pytest.raises(RuntimeError) as excinfo:
            read_preprocessor_bundle_hash(
                path, consumer_command="r14-cli lock-plan")
        msg = str(excinfo.value)
        assert "preprocessor_bundle_hash" in msg
        assert str(path) in msg
        assert "r14-cli lock-plan" in msg

    def test_legacy_bundle_hash_key_cannot_impersonate(
            self, real_identity, tmp_path):
        """R12 缺陷回归锁:仅含 'bundle_hash' 的 artifact 必须被拒绝。"""
        from rl_curriculum.curriculum261_r14_plan import (
            read_preprocessor_bundle_hash,
        )

        _, identity, _ = real_identity
        wrong = {"bundle_hash": identity[
            "preprocessor_bundle_hash"]}
        path = tmp_path / "preprocessor_bundle_calibration.json"
        path.write_text(json.dumps(wrong), encoding="utf-8")
        with pytest.raises(RuntimeError, match="preprocessor_bundle_hash"):
            read_preprocessor_bundle_hash(
                path, consumer_command="r14-cli lock-plan")

    def test_bad_value_fail_closed(self, real_identity, tmp_path):
        from rl_curriculum.curriculum261_r14_plan import (
            read_preprocessor_bundle_hash,
        )

        _, identity, _ = real_identity
        bad = dict(identity)
        bad["preprocessor_bundle_hash"] = "not-a-digest"
        path = tmp_path / "preprocessor_bundle_calibration.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(RuntimeError, match="r4pb-"):
            read_preprocessor_bundle_hash(
                path, consumer_command="r14-cli lock-plan")

    def test_unparseable_fail_closed(self, tmp_path):
        from rl_curriculum.curriculum261_r14_plan import (
            read_preprocessor_bundle_hash,
        )

        path = tmp_path / "preprocessor_bundle_calibration.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(RuntimeError):
            read_preprocessor_bundle_hash(
                path, consumer_command="r14-cli lock-plan")

    def test_subprocess_independent_read(self, real_identity):
        """独立进程读取(不依赖测试进程内存;与 CLI 子进程同构)。"""
        import rl_curriculum

        _, identity, path = real_identity
        proj = Path(rl_curriculum.__file__).resolve().parents[2]
        code = (
            "import json,sys;sys.path.insert(0, sys.argv[2]);"
            "from rl_curriculum.curriculum261_r14_plan import "
            "read_preprocessor_bundle_hash;"
            "print(read_preprocessor_bundle_hash("
            "sys.argv[1], consumer_command='subproc-test'))")
        res = subprocess.run(
            [sys.executable, "-c", code, str(path), str(proj / "src")],
            capture_output=True, text=True, timeout=300)
        assert res.returncode == 0, res.stderr[-500:]
        assert (res.stdout.strip().splitlines()[-1]
                == identity["preprocessor_bundle_hash"])


class TestCliIndependentProcess:
    def test_namespace_integrity_cli_rc0(self, tmp_path):
        import rl_curriculum

        proj = Path(rl_curriculum.__file__).resolve().parents[2]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(proj / "src")
        res = subprocess.run(
            [sys.executable, "-m",
             "rl_curriculum.curriculum261_r14_cli",
             "namespace-integrity", "--out-dir", str(tmp_path)],
            capture_output=True, text=True, timeout=1800, env=env,
            cwd=str(proj))
        assert res.returncode == 0, res.stdout[-800:] + res.stderr[-800:]

    def test_audit_without_freeze_fails_closed(self, tmp_path):
        import rl_curriculum

        proj = Path(rl_curriculum.__file__).resolve().parents[2]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(proj / "src")
        env["CURRICULUM261_R14_LOCK_DIR"] = str(tmp_path)
        res = subprocess.run(
            [sys.executable, "-m",
             "rl_curriculum.curriculum261_r14_cli",
             "audit", "--out-dir", str(tmp_path)],
            capture_output=True, text=True, timeout=600, env=env,
            cwd=str(proj))
        assert res.returncode == 1
        assert "fail closed" in (res.stdout + res.stderr)

    def test_real_artifact_rehearsal_registered(self):
        import rl_curriculum

        proj = Path(rl_curriculum.__file__).resolve().parents[2]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(proj / "src")
        res = subprocess.run(
            [sys.executable, "-m",
             "rl_curriculum.curriculum261_r14_cli", "--help"],
            capture_output=True, text=True, timeout=300, env=env,
            cwd=str(proj))
        assert res.returncode == 0
        for cmd in ("real-artifact-rehearsal", "artifact-interface-audit",
                    "lock-plan", "preflight-sealed", "qualify"):
            assert cmd in res.stdout


class TestDesignPayloadRehearsalOverrides:
    def _payload(self, **overrides):
        from rl_curriculum.curriculum261_r14_design import (
            design_plan_payload_r14,
        )

        kwargs = dict(
            baseline_commit="test-baseline",
            vendor_pin="52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
            v2_contract_digest="r4v2-test",
            prior_r2_plan_digest="qp-test",
            prior_diag262r2_plan_digest="dp-test",
            cue_audit={"p_contract": 0.95, "audit_digest": "r14ca-test",
                       "pass": True},
            preplan_smoke_identity={"sentinel_digest": "r14smoke-test"},
            dependency_identity={"test": True},
            artifact_writer_identity={"test": True},
            preplan_rehearsal_digest="r14pr-test",
            r8_abort_evidence={"test": True},
        )
        kwargs.update(overrides)
        return design_plan_payload_r14(**kwargs)

    def test_rehearsal_overrides_recorded(self):
        plan = self._payload(
            design_namespaces=("rt_design_matched_main_r14",
                               "rt_design_matched_validation_r14"),
            semantic_namespaces=("rt_semantic_design_main_r14",
                                 "rt_semantic_design_validation_r14"),
            independent_namespace="rt_design_independent_r14",
            rehearsal=True)
        assert plan["rehearsal"] is True
        assert plan["design_data"]["corpora"] == [
            "rt_design_matched_main_r14", "rt_design_matched_validation_r14"]
        assert plan["semantic_corpora"]["namespaces"] == [
            "rt_semantic_design_main_r14",
            "rt_semantic_design_validation_r14"]
        assert plan["independent_marginal_guard"][
            "namespace"] == "rt_design_independent_r14"
        # 样本量不随 rehearsal 缩小(§四-4:只允许换 namespace)
        assert plan["design_data"][
            "blocks_per_candidate_per_corpus"] == 40
        assert plan["semantic_corpora"]["blocks_per_corpus"] == 160

    def test_formal_defaults_unchanged(self):
        plan = self._payload()
        assert plan["rehearsal"] is False
        assert plan["design_data"]["corpora"] == [
            "design_r14_matched_main", "design_r14_matched_validation"]
        assert plan["semantic_corpora"]["namespaces"] == [
            "cue_semantic_design_main_r14",
            "cue_semantic_design_validation_r14"]

    def test_two_corpus_enforced(self):
        with pytest.raises(RuntimeError, match="各为 2"):
            self._payload(design_namespaces=("only_one_r14",))

    def test_rt_semantic_map_explicit(self):
        from rl_curriculum.curriculum261_r14_design import (
            semantic_artifact_filename_r14,
        )

        assert semantic_artifact_filename_r14(
            "rt3_semantic_main_r14") == "rt_semantic_main.json"
        assert semantic_artifact_filename_r14(
            "rt3_semantic_final_r14") == "rt_semantic_final.json"
        assert semantic_artifact_filename_r14(
            "rt_semantic_design_main_r14") == "rt_semantic_design_main.json"
        with pytest.raises(RuntimeError):
            semantic_artifact_filename_r14("unknown_semantic_ns_r14")


class TestExposureOneShot:
    def test_double_create_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R14_LOCK_DIR", str(tmp_path))
        from rl_curriculum.curriculum261_r14_namespaces import (
            write_qualification_r14_exposure,
        )

        write_qualification_r14_exposure("r14qp-test", "running")
        with pytest.raises(RuntimeError, match="已存在"):
            write_qualification_r14_exposure("r14qp-test", "running")


class TestArtifactInterfaceAudit:
    def test_audit_table_structure(self):
        from rl_curriculum.curriculum261_r14_cli import (
            artifact_interface_audit,
        )

        audit = artifact_interface_audit()
        assert audit["format"] == "cur261-r14-artifact-interface-audit-v1"
        edges = {e["edge"] for e in audit["edges"]}
        assert "calibration-bundle→lock-plan" in edges
        assert "sealed-attestation→qualify-init" in edges
        assert "qualify-outputs→ppo-smoke+downstream" in edges
        # R12 缺陷边必须声明 r12_defect 与 r14_closure
        bundle_edge = next(e for e in audit["edges"]
                           if e["edge"] == "calibration-bundle→lock-plan")
        assert "bundle_hash" in bundle_edge["r12_defect"]
        assert bundle_edge["r14_closure"]

    def test_rehearsal_steps_declared(self):
        from rl_curriculum.curriculum261_r14_cli import (
            artifact_interface_audit,
        )

        audit = artifact_interface_audit()
        steps = {e["rehearsal_step"] for e in audit["edges"]}
        allowed = {"provenance-lock", "determinism-matrix", "audit",
                   "cue-audit", "design-plan-lock", "design",
                   "calibrate", "preflight-sealed", "lock-plan",
                   "qualify", "smoke", "full-cold-reader-check"}
        assert steps <= allowed
        # §九-5:full-cold reader 边必须指向真实 rehearsal 步骤
        # (R13 曾标记 smoke "同时覆盖 full-cold" 而未实际执行)
        smoke_edge = next(
            e for e in audit["edges"]
            if e["edge"] == "smoke-outputs→downstream")
        assert smoke_edge["rehearsal_step"] == "full-cold-reader-check"
        assert "r13_defect" in smoke_edge
