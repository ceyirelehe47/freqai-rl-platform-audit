# -*- coding: utf-8 -*-
"""R14 §十-2:单步正式命令执行器。

subprocess 运行正式 CLI,独立保存 stdout/stderr,并把 argv/cwd/
environment identity/start-end UTC/rc/stdout+stderr sha256/输入输出
artifact digest 追加进 r14_formal_log_manifest.jsonl(append-only)。
formal_chain.sh 的每一步都经本执行器;任何一步 rc!=0 即停。

Commit A 冻结文件(§六);失败后不得创建新的执行/记录脚本。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

LOG_MANIFEST_NAME = "r14_formal_log_manifest.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: r14_run_step.py <step> <cli-args...> "
              "[--input p ...] [--output p ...]", file=sys.stderr)
        return 2
    step = sys.argv[1]
    rest = sys.argv[2:]
    inputs: list[str] = []
    outputs: list[str] = []
    cli_args: list[str] = []
    i = 0
    while i < len(rest):
        if rest[i] == "--input" and i + 1 < len(rest):
            inputs.append(rest[i + 1])
            i += 2
        elif rest[i] == "--output" and i + 1 < len(rest):
            outputs.append(rest[i + 1])
            i += 2
        else:
            cli_args.append(rest[i])
            i += 1

    home = Path.home() / "projects/crypto_rl"
    log_dir = home / "r14_formal_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = log_dir / f"{step}.log"
    err_log = log_dir / f"{step}.err"

    argv = [sys.executable, "-m",
            "rl_curriculum.curriculum261_r14_cli", *cli_args]
    print(f"=== [{step}] start {_now()} ===")
    start = _now()
    proc = subprocess.run(argv, cwd=str(home), text=True,
                          capture_output=True)
    end = _now()
    out_log.write_text(proc.stdout, encoding="utf-8")
    err_log.write_text(proc.stderr, encoding="utf-8")
    tail = proc.stdout.strip().splitlines()[-3:]
    for line in tail:
        print(f"  {line}")
    print(f"=== [{step}] rc={proc.returncode} end {_now()} ===")

    import hashlib

    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    from rl_curriculum.curriculum261_r14_cli import _env_identity

    record = {
        "step": step,
        "argv": argv,
        "cwd": str(home),
        "env": _env_identity(),
        "start_utc": start,
        "end_utc": end,
        "rc": proc.returncode,
        "stdout_path": str(out_log),
        "stdout_sha256": _sha(out_log),
        "stdout_bytes": out_log.stat().st_size,
        "stderr_path": str(err_log),
        "stderr_sha256": _sha(err_log),
        "stderr_bytes": err_log.stat().st_size,
        "input_artifacts": [{"path": p, "sha256": _sha(Path(p))}
                            for p in inputs if Path(p).is_file()],
        "output_artifacts": [{"path": p, "sha256": _sha(Path(p))}
                             for p in outputs if Path(p).is_file()],
    }
    with (log_dir / LOG_MANIFEST_NAME).open("a",
                                            encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
