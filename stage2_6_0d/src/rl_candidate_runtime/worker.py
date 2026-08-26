"""候选 worker:沙箱内的 JSON-lines 执行器(阶段 2.6.0b 工作包 B/C)。

协议(candidate-worker-v2):
- 启动:python -m rl_candidate_runtime.worker <checkpoint 中性路径>
  <expected_charter_hash> <expected_observation_schema_hash>
- 请求/响应(每行一个 JSON):
  {"op": "reset"}          -> {"ok": true}          (无任何 Episode 身份 token)
  {"op": "act", "obs":[…]} -> {"action": 0|1}
  {"op": "close"}          -> {"ok": true} 后退出
- 任何候选侧异常只回 {"error": "candidate-error-redacted", "stage": …},
  绝不回传 traceback/环境/文件内容。

工作包 B:reset 消息逐字节为 {"op": "reset"}——不携带 derived_seed /
episode_id / seed / spec_hash / 任何稳定题目身份信息。

工作包 C7(输出协议限制):stdout 每行长度上限
MAX_RESPONSE_LINE_BYTES;非法 op / 非法 observation / 超长响应一律
fail closed(退出非零,评估主进程据此 EXAM_INVALID)。
"""

from __future__ import annotations

import json
import sys

from rl_candidate_runtime import WORKER_PROTOCOL
from rl_candidate_runtime.guard import (
    CandidateCheckpointError,
    load_and_verify_sidecar,
)

MAX_RESPONSE_LINE_BYTES = 4096
MAX_OBS_DIM = 4096


def _emit(payload: dict) -> None:
    line = json.dumps(payload)
    if len(line.encode("utf-8")) > MAX_RESPONSE_LINE_BYTES:
        # 不可能发生(payload 受控);仍 fail closed 防御性处理
        print(json.dumps({"error": "candidate-error-redacted",
                          "stage": "response-limit"}), flush=True)
        raise SystemExit(7)
    print(line, flush=True)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        _emit({"error": "candidate-error-redacted",
               "stage": "usage"})
        return 2
    checkpoint_path, expected_charter, expected_obs = argv[1], argv[2], argv[3]
    try:
        from rl_candidate_runtime.guard import load_candidate_model

        manifest = load_and_verify_sidecar(
            checkpoint_path,
            expected_charter_hash=expected_charter,
            expected_observation_schema_hash=expected_obs,
        )
        model = load_candidate_model(checkpoint_path, device="cpu")
    except CandidateCheckpointError:
        # 不回传 checkpoint 内容/路径细节;主进程只看到脱敏标记
        _emit({"error": "candidate-error-redacted", "stage": "load"})
        return 3
    except Exception:  # noqa: BLE001 - worker 侧异常一律脱敏
        _emit({"error": "candidate-error-redacted", "stage": "load"})
        return 3
    expected_dim = manifest.get("observation_dim")
    if not isinstance(expected_dim, int) or expected_dim < 1:
        _emit({"error": "candidate-error-redacted", "stage": "sidecar-dim"})
        return 3

    for line in sys.stdin:
        if len(line.encode("utf-8")) > MAX_RESPONSE_LINE_BYTES:
            _emit({"error": "candidate-error-redacted",
                   "stage": "request-limit"})
            return 8
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _emit({"error": "candidate-error-redacted", "stage": "protocol"})
            return 4
        # 工作包 B:reset 请求必须逐字节为 {"op": "reset"};
        # 携带任何额外字段(derived_seed/episode_id/seed/spec_hash/...)
        # 一律视为协议违规(fail closed)
        op = req.get("op")
        if op == "reset":
            if set(req.keys()) != {"op"}:
                _emit({"error": "candidate-error-redacted",
                       "stage": "reset-identity-token"})
                return 9
            _emit({"ok": True})
            continue
        if op == "act":
            obs = req.get("obs")
            if (not isinstance(obs, list) or not obs
                    or len(obs) > MAX_OBS_DIM
                    or not all(isinstance(x, (int, float)) for x in obs)):
                _emit({"error": "candidate-error-redacted", "stage": "obs"})
                return 6
            if len(obs) != expected_dim:
                _emit({"error": "candidate-error-redacted",
                       "stage": "obs-dim"})
                return 6
            try:
                import numpy as np

                arr = np.asarray(obs, dtype=np.float32)
                action, _ = model.predict(arr.reshape(1, -1),
                                          deterministic=True)
                _emit({"action": int(np.asarray(action).reshape(-1)[0])})
            except Exception:  # noqa: BLE001 - 决不回传候选 traceback
                _emit({"error": "candidate-error-redacted", "stage": "act"})
                return 5
            continue
        if op == "close":
            _emit({"ok": True})
            return 0
        _emit({"error": "candidate-error-redacted", "stage": "op"})
        return 4
    return 0


if __name__ == "__main__":
    print(json.dumps({"protocol": WORKER_PROTOCOL}), flush=True)
    raise SystemExit(main(sys.argv))
