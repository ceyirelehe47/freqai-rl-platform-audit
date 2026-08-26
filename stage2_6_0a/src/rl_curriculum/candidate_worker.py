"""阶段 2.6.0a 工作包 A5:候选 checkpoint 子进程隔离执行器。

正式 hidden exam 中候选在独立子进程运行,双方只通过 stdin/stdout 的
JSON-lines 协议通信:
- 候选进程只收到:observation 数组、checkpoint 路径、必要运行依赖;
- 隐藏生成器、hidden frame、考试 spec、详细指标全部留在评估主进程;
- 候选进程的启动环境被清洗(不通过环境变量泄漏 seed/family/split/
  pack 路径等);
- 候选异常不携带隐藏参数 traceback:worker 只回 {"error":
  "candidate-error-redacted"},stderr 由父进程捕获但不进入任何输出
  (仅记录"存在已脱敏 stderr"布尔)。

父进程侧适配器 SubprocessCandidate 实现正式 CandidatePolicy 接口
(reset_episode/act/close),评估器对其与进程内候选一视同仁。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import numpy as np

from rl_curriculum.policy_api import CandidatePolicy

WORKER_PROTOCOL = "candidate-worker-v1"

# 启动环境清洗:移除可能携带考试信息的变量名模式(白名单思路:
# 只保留运行时必需变量,凡命中模式的一律删除)
_ENV_DENY_PATTERNS: tuple[str, ...] = (
    "SEED", "FAMILY", "SPLIT", "PACK", "EXAM", "CHARTER", "HIDDEN",
    "PARAMS", "NULL", "VERDICT",
)


class CandidateSubprocessError(RuntimeError):
    """候选子进程错误(已脱敏:不含隐藏参数/traceback)。"""


def scrub_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """清洗子进程环境:删除命中泄漏模式的变量(值也不复制)。"""
    base = dict(env if env is not None else os.environ)
    scrubbed = {}
    for key, value in base.items():
        if any(pat in key.upper() for pat in _ENV_DENY_PATTERNS):
            continue
        scrubbed[key] = value
    return scrubbed


def _worker_main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(json.dumps({
            "error": "candidate-error-redacted",
            "detail": "usage: candidate_worker <checkpoint> "
                      "<expected_charter_hash> "
                      "<expected_observation_schema_hash>",
        }), flush=True)
        return 2
    checkpoint_path, expected_charter, expected_obs = argv[1], argv[2], argv[3]
    try:
        from rl_curriculum.policies import SB3CheckpointPolicy

        policy = SB3CheckpointPolicy(
            checkpoint_path,
            expected_charter_hash=expected_charter,
            expected_observation_schema_hash=expected_obs,
        )
    except Exception:  # noqa: BLE001 - worker 侧异常一律脱敏
        # 不回传 traceback/checkpoint 内容;主进程只看到红acted标记
        print(json.dumps({
            "error": "candidate-error-redacted",
            "stage": "load",
        }), flush=True)
        return 3

    for line in sys.stdin:
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({
                "error": "candidate-error-redacted", "stage": "protocol",
            }), flush=True)
            return 4
        op = req.get("op")
        try:
            if op == "act":
                obs = np.asarray(req["obs"], dtype=np.float32)
                action = int(policy.act(obs))
                print(json.dumps({"action": action}), flush=True)
            elif op == "reset":
                policy.reset_episode(int(req.get("derived_seed", 0)))
                print(json.dumps({"ok": True}), flush=True)
            elif op == "close":
                policy.close()
                print(json.dumps({"ok": True}), flush=True)
                return 0
            else:
                print(json.dumps({
                    "error": "candidate-error-redacted", "stage": "op",
                }), flush=True)
                return 5
        except Exception:  # noqa: BLE001 - 决不回传候选 traceback
            print(json.dumps({
                "error": "candidate-error-redacted", "stage": "act",
            }), flush=True)
            return 6
    return 0


class SubprocessCandidate(CandidatePolicy):
    """子进程候选适配器:正式 CandidatePolicy 接口,隔离执行。

    - 不向子进程传递 episode/hidden/seed/family/split(只有 obs 数组);
    - 子进程环境经 scrub_environment 清洗;
    - 候选异常 -> CandidateSubprocessError(脱敏);
    - stderr 捕获但不转发(仅记录存在标志)。
    """

    name = "subprocess_candidate"

    def __init__(
        self,
        checkpoint_path,
        *,
        expected_charter_hash: str,
        expected_observation_schema_hash: str,
        python: str = sys.executable,
        env: dict[str, str] | None = None,
    ):
        import rl_curriculum

        self.checkpoint_path = str(checkpoint_path)
        child_env = scrub_environment(env)
        # 子进程需要能导入 rl_curriculum(sys.path 插入不跨进程):
        # 把 src 根加入 PYTHONPATH;该变量不携带任何考试信息
        src_root = str(
            __import__("pathlib").Path(rl_curriculum.__file__).resolve()
            .parent.parent)
        child_env["PYTHONPATH"] = os.pathsep.join(
            [src_root, child_env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        self._proc = subprocess.Popen(
            [
                python, "-m", "rl_curriculum.candidate_worker",
                self.checkpoint_path,
                expected_charter_hash,
                expected_observation_schema_hash,
            ],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env,
            text=True, bufsize=1,
        )
        self._stderr_present = False

    @property
    def candidate_stderr_redacted(self) -> bool:
        return self._stderr_present

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            assert self._proc.stdin is not None and self._proc.stdout is not None
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        except (BrokenPipeError, OSError, AssertionError) as exc:
            raise CandidateSubprocessError(
                "候选子进程通信失败(已脱敏:无隐藏参数)") from exc
        if not line:
            self._stderr_present = True
            raise CandidateSubprocessError(
                "候选子进程提前退出(已脱敏:无隐藏参数/traceback)")
        try:
            reply = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CandidateSubprocessError(
                "候选子进程回复无法解析(已脱敏)") from exc
        if "error" in reply:
            raise CandidateSubprocessError(
                f"候选子进程错误(已脱敏): {reply['error']}"
                f"/stage={reply.get('stage', '?')}")
        return reply

    def reset_episode(self, derived_seed: int) -> None:
        self._send({"op": "reset", "derived_seed": int(derived_seed)})

    def act(self, observation: np.ndarray) -> int:
        obs = np.asarray(observation, dtype=np.float32)
        return int(self._send({"op": "act", "obs": obs.tolist()})["action"])

    def close(self) -> None:
        try:
            self._send({"op": "close"})
            self._proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - 清理阶段不抛
            self._proc.terminate()
        finally:
            for stream in (self._proc.stdin, self._proc.stdout,
                           self._proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass


if __name__ == "__main__":
    raise SystemExit(_worker_main(sys.argv))
