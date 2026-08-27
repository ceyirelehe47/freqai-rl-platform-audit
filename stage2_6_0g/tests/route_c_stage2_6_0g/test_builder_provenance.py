"""P1/P2:builder 产物来源证明(核心攻击面)。

- mock/私有 builder 重放产物 pack_hash == commitment.pack_hash;
- None 入口私有 builder 与公开 mock pack 组合 -> 产物来源证明拒绝
  (P2 攻击闭环);
- 产物不同的真实 builder -> 拒绝;
- 冻结请求哈希对账(请求被替换 -> 拒绝)。
"""

from __future__ import annotations

import pytest

from rl_curriculum.builder_provenance import (
    BuilderProvenanceError,
    verify_builder_provenance,
)


class _Commit:
    """最小承诺替身(只取 provenance 对账所需字段)。"""

    def __init__(self, pack_hash, request_hash):
        self.pack_hash = pack_hash
        self.builder_build_request_hash = request_hash


def test_mock_provenance_passes(sealed_exam_env, duration_contract):
    """mock 链:重放产物 == 承诺绑定 pack(文件身份 + 产物来源双证明;
    mock 通道的冻结构建输入含 pack 规范载荷,按载荷确定性重建)。"""
    env = sealed_exam_env
    report = verify_builder_provenance(
        env["provider"], env["commitment"], pack=env["pack"],
        duration_contract=duration_contract,
        allow_mock_pack_payload=True)
    assert report["status"] == "ok"
    assert report["pack_hash_match"] is True
    assert report["replay_pack_hash"] == env["commitment"].pack_hash
    assert report["build_request_hash"].startswith("nbr-")


def test_private_provenance_passes(sealed_exam_env, private_builder_a,
                                   duration_contract):
    """私有 builder A(真实构建):承诺/重放/Provider 三方一致。"""
    from rl_curriculum.builder_provenance import frozen_build_request_hash

    env = sealed_exam_env
    # 用私有 Provider 为同一 pack 重新派生请求(承诺的 nbr- 对得上)
    req = private_builder_a.frozen_build_request(
        env["pack"], duration_contract)
    commit = _Commit(env["commitment"].pack_hash,
                     frozen_build_request_hash(req))
    report = verify_builder_provenance(
        private_builder_a, commit, pack=env["pack"],
        duration_contract=duration_contract)
    assert report["status"] == "ok"
    assert report["replay_pack_hash"] == env["pack"].pack_hash()


def test_p2_none_entry_with_mock_pack_rejected(sealed_exam_env,
                                               private_builder_none,
                                               duration_contract):
    """P2 核心攻击:None 入口私有 builder + 公开 mock pack 的承诺 ->
    产物来源证明拒绝(builder 实际执行返回 None)。

    2.6.0f 里该组合能通过 formal verification(verify 只对账 npb-);
    2.6.0g 在候选加载前实际执行 builder,通道关闭。
    """
    from rl_curriculum.builder_provenance import frozen_build_request_hash

    env = sealed_exam_env
    req = private_builder_none.frozen_build_request(
        env["pack"], duration_contract)
    commit = _Commit(env["commitment"].pack_hash,
                     frozen_build_request_hash(req))
    with pytest.raises(BuilderProvenanceError, match="返回 None"):
        verify_builder_provenance(
            private_builder_none, commit, pack=env["pack"],
            duration_contract=duration_contract)


def test_wrong_pack_builder_rejected(sealed_exam_env,
                                     private_builder_wrong_pack,
                                     duration_contract):
    """真实构建但产物不同的 builder(5m pack vs 15m 承诺)-> 拒绝
    (文件身份正确但产物来源不成立;P1 核心)。"""
    from rl_curriculum.builder_provenance import frozen_build_request_hash

    env = sealed_exam_env
    req = private_builder_wrong_pack.frozen_build_request(
        env["pack"], duration_contract)
    commit = _Commit(env["commitment"].pack_hash,
                     frozen_build_request_hash(req))
    with pytest.raises(BuilderProvenanceError, match="pack_hash.*不一致"):
        verify_builder_provenance(
            private_builder_wrong_pack, commit, pack=env["pack"],
            duration_contract=duration_contract)


def test_request_hash_mismatch_rejected(sealed_exam_env,
                                        private_builder_a,
                                        duration_contract):
    """承诺绑定的请求哈希与重放派生不一致(请求被替换)-> 拒绝。"""
    env = sealed_exam_env
    commit = _Commit(env["commitment"].pack_hash,
                     "nbr-" + "f" * 64)  # 伪造的请求哈希
    with pytest.raises(BuilderProvenanceError, match="请求哈希.*不一致"):
        verify_builder_provenance(
            private_builder_a, commit, pack=env["pack"],
            duration_contract=duration_contract)


def test_provider_without_entrypoint_rejected(sealed_exam_env,
                                              duration_contract):
    """Provider 未实现 builder_entrypoint -> 产物来源无法证明。"""

    class _OldProvider:
        def builder_identity(self):
            return sealed_exam_env["provider"].builder_identity()

    with pytest.raises(BuilderProvenanceError, match="无法提供"):
        verify_builder_provenance(
            _OldProvider(), sealed_exam_env["commitment"],
            pack=sealed_exam_env["pack"],
            duration_contract=duration_contract)


def test_private_request_with_payload_rejected(sealed_exam_env,
                                               private_builder_a,
                                               duration_contract):
    """硬闸:私有 builder 的请求携带 mock_pack_payload(pack 规范
    重放载荷)-> 拒绝。私有通道的重放必须真实构建,不得照抄 pack
    内容;载荷只属于公开 mock 组装通道。"""
    import json as _json

    from rl_curriculum.builder_provenance import (
        frozen_build_request_hash,
    )

    env = sealed_exam_env

    class _PayloadPrivate:
        """模拟被篡改的私有 Provider:请求里混入 pack 载荷。"""

        def __init__(self, inner):
            self._inner = inner

        def builder_identity(self):
            return self._inner.builder_identity()

        def builder_entrypoint(self):
            return self._inner.builder_entrypoint()

        def frozen_build_request(self, pack, dc):
            req = dict(self._inner.frozen_build_request(pack, dc))
            req["mock_pack_payload"] = _json.loads(pack.to_json())
            return req

    sneaky = _PayloadPrivate(private_builder_a)
    req = sneaky.frozen_build_request(env["pack"], duration_contract)
    commit = _Commit(env["commitment"].pack_hash,
                     frozen_build_request_hash(req))
    with pytest.raises(BuilderProvenanceError, match="mock_pack_payload"):
        verify_builder_provenance(
            sneaky, commit, pack=env["pack"],
            duration_contract=duration_contract)
    # 公开 mock 通道明确放行(allow_mock_pack_payload=True)
    report = verify_builder_provenance(
        env["provider"], env["commitment"], pack=env["pack"],
        duration_contract=duration_contract,
        allow_mock_pack_payload=True)
    assert report["replay_mode"] == "mock_payload_assembly"
    assert report["pack_hash_match"] is True


def test_commitment_carries_request(sealed_exam_env):
    """v7 承诺携带完整冻结构建请求与 nbr- 哈希(重放输入被承诺绑定)。"""
    env = sealed_exam_env
    from rl_curriculum.builder_provenance import (
        frozen_build_request_hash,
    )

    assert env["commitment"].builder_build_request_hash.startswith("nbr-")
    assert (frozen_build_request_hash(
        env["commitment"].builder_build_request)
        == env["commitment"].builder_build_request_hash)
    req = env["commitment"].builder_build_request
    assert req["builder_manifest_hash"] == \
        env["commitment"].pack_builder_code_hash
    assert req["duration_contract_hash"] == \
        env["commitment"].null_duration_contract_hash
