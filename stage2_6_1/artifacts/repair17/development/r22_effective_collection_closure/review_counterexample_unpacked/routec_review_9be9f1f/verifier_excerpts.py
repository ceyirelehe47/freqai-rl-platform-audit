"""Function excerpts transcribed from pinned GitHub source (not full module).
Repository: ceyirelehe47/freqai-rl-platform-audit
Commit: 9be9f1f61075936a20d27254e4cff6462959e3f6
File: stage2_6_1/src/rl_curriculum/curriculum261_r17_admission_substance.py
Blob: 613007433bf48fcfb6c0cb4e4b998484aa0ee3e3
The isolated harness exercises only these functions, not WSL admission.
Docstrings/comments shortened here; executable function bodies retained.
"""
from __future__ import annotations
import ast, json, re
from pathlib import Path

_ARGV_FORBIDDEN = frozenset({
    "-k", "-m", "-M", "--marker", "--deselect", "--ignore",
    "--ignore-glob", "--lf", "--last-failed", "--ff", "--failed-first",
    "-x", "--exitfirst", "--maxfail", "--stepwise", "--sw", "-p",
    "--rootdir", "--pyargs",
})
_VALUE_FLAGS = frozenset({"--junitxml", "--timeout", "-n"})
_CONFT_HOOKS = frozenset({"pytest_collection_modifyitems", "pytest_ignore_collect"})
_DEPLOYED_TEST_ROOT = "tests/route_c_stage2_6_1/"
_ENV_IDENTITY_KEYS = ("python_version", "pytest_version_output", "pytest_addopts", "pytest_plugins_env", "config_scan")
_COLLECTED_ID_RE = re.compile(r"^tests/route_c_stage2_6_1/\S+\.py::.*$")
_OUT_OF_ROOT_ID_RE = re.compile(r"^\s*\S+\.py::\S+")
_COLLECT_SUMMARY_RE = re.compile(r"^(\d+) tests? collected in ")
_PASSED_SUMMARY_RE = re.compile(r"(\d+) passed(?:, (\d+) skipped)?[^\n]*\bin\b")

class SubstanceError(RuntimeError):
    pass

def _param_base(node_id: str) -> str:
    head, sep, last = node_id.rpartition("::")
    if "[" in last:
        last = last[:last.index("[")]
    return head + sep + last if sep else last

def _reject_config_filters(path: Path, data: bytes) -> None:
    if path.name == "conftest.py":
        try:
            module = ast.parse(data)
        except SyntaxError as exc:
            raise SubstanceError(
                f"regression_config_unparseable:{path.name}") from exc
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name in _CONFT_HOOKS:
                raise SubstanceError(
                    "regression_config_filter_hook:" + node.name)
        return
    for raw in data.replace(b"\r", b"").splitlines():
        line = raw.strip().decode("utf-8", "replace")
        key = line.split("=", 1)[0].split(":", 1)[0].strip()
        if key not in ("addopts", "-addopts"):
            continue
        value = line.split("=", 1)[-1] if "=" in line else line
        for token in value.replace(":", " ").split():
            if token.split("=", 1)[0] in _ARGV_FORBIDDEN:
                raise SubstanceError(
                    "regression_config_addopts_filter:" + token)

def parse_collection_stdout(text: str) -> list[str]:
    ids: list[str] = []
    counts: list[int] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r").strip()
        if not line:
            continue
        matched = _COLLECT_SUMMARY_RE.match(line)
        if matched:
            counts.append(int(matched.group(1)))
            continue
        if _COLLECTED_ID_RE.match(line):
            ids.append(line)
            continue
        if _OUT_OF_ROOT_ID_RE.match(line):
            raise SubstanceError(
                "regression_collection_scope_leak:" + line[:160])
    if len(counts) != 1:
        raise SubstanceError(
            "regression_collection_summary_lines:" + str(len(counts)))
    if counts[0] != len(ids):
        raise SubstanceError(
            f"regression_collection_count_mismatch"
            f"({counts[0]}!={len(ids)})")
    if not ids:
        raise SubstanceError("regression_collection_empty")
    if len(set(ids)) != len(ids):
        raise SubstanceError("regression_collection_duplicate")
    return ids

def _verify_run_argv(command, *, collect_only: bool,
                     positionals_rule) -> None:
    if not (isinstance(command, list) and len(command) >= 3
            and all(isinstance(a, str) and a for a in command)
            and command[1] == "-m" and command[2] == "pytest"):
        raise SubstanceError("regression_run_command_shape_invalid")
    args = command[3:]
    positionals: list[str] = []
    expect_value = False
    for tok in args:
        if expect_value:
            expect_value = False
            continue
        if tok.startswith("-"):
            name = tok.split("=", 1)[0]
            if name in _ARGV_FORBIDDEN:
                raise SubstanceError(f"regression_run_argv_filter:{name}")
            if "=" not in tok and name in _VALUE_FLAGS:
                expect_value = True
            continue
        positionals.append(tok)
    if collect_only and "--collect-only" not in args:
        raise SubstanceError("regression_run_collect_only_missing")
    if not collect_only and "--collect-only" in args:
        raise SubstanceError("regression_run_collect_only_unexpected")
    if positionals_rule == "under_root":
        if not positionals:
            raise SubstanceError("regression_run_shard_targets_missing")
        for target in positionals:
            if not target.startswith(_DEPLOYED_TEST_ROOT):
                raise SubstanceError(
                    "regression_run_target_outside_root:" + target)
    else:
        if positionals != list(positionals_rule):
            raise SubstanceError(
                "regression_run_argv_target_mismatch:"
                + json.dumps(positionals[:3]))

def _verify_run_identity(entries: list, reference: dict, label: str) -> None:
    for entry in entries:
        for key in ("interpreter", "cwd"):
            if entry.get(key) != reference.get(key):
                raise SubstanceError(f"regression_run_identity_mismatch:{key}")
        for key in _ENV_IDENTITY_KEYS:
            if entry.get("env", {}).get(key) != \
                    reference.get("env", {}).get(key):
                raise SubstanceError(
                    f"regression_run_identity_mismatch:{key}")

def _verify_execution_summary(stdout: bytes, aggregate: dict) -> None:
    text = stdout.decode("utf-8", errors="replace")
    found = _PASSED_SUMMARY_RE.findall(text)
    want = (aggregate["tests"] - aggregate["failures"]
            - aggregate["errors"] - aggregate["skipped"],
            aggregate["skipped"])
    if found:
        passed, skipped = (int(found[-1][0]), int(found[-1][1] or "0"))
    else:
        skipped_only = re.findall(r"(\d+) skipped[^\n]*\bin\b", text)
        if not skipped_only:
            raise SubstanceError(
                "regression_execution_stdout_summary_missing")
        passed, skipped = 0, int(skipped_only[-1])
    if (passed, skipped) != want:
        raise SubstanceError(
            "regression_execution_stdout_summary_mismatch:"
            + json.dumps({"stdout": [passed, skipped], "junit": want}))
