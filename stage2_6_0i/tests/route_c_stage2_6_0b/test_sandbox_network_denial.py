"""工作包 C8/C5:网络隔离(本机/外部/DNS 全部拒绝)。"""

from __future__ import annotations

import json
import socket

import pytest

from conftest import build_probe_code, run_candidate_in_sandbox


def _parse(proc):
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"probe 无输出: rc={proc.returncode} err={proc.stderr[-500:]}"
    return json.loads(lines[-1])


@pytest.fixture(scope="module")
def local_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(4)
    port = s.getsockname()[1]
    yield port
    s.close()


_NET_PROBE = '''
import socket
def try_connect(host, port, timeout=3):
    try:
        c = socket.create_connection((host, port), timeout=timeout)
        c.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "err": type(e).__name__,
                "errno": getattr(e, "errno", None)}
def try_resolve(host):
    try:
        return {"ok": True, "addrs": socket.getaddrinfo(host, 80)[:1]}
    except Exception as e:
        return {"ok": False, "err": type(e).__name__}
report["extra"]["loopback"] = try_connect("127.0.0.1", __PORT__)
report["extra"]["external_ip"] = try_connect("93.184.216.34", 80)
report["extra"]["dns"] = try_resolve("example.com")
'''


def test_loopback_connect_denied(sandbox_checkpoint, local_listener):
    code = _NET_PROBE.replace("__PORT__", str(local_listener))
    proc = run_candidate_in_sandbox(sandbox_checkpoint,
                                    probe_code=build_probe_code(
                                        extra_code=code))
    report = _parse(proc)
    r = report["extra"]["loopback"]
    assert not r["ok"], f"候选可连接本机服务: {r}"


def test_external_connect_denied(sandbox_checkpoint):
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(
            extra_code=_NET_PROBE.replace("__PORT__", "80")))
    report = _parse(proc)
    assert not report["extra"]["external_ip"]["ok"], (
        f"候选可连接外部地址: {report['extra']['external_ip']}")
    # 空网络命名空间:除 down 的 lo 外无任何接口/路由
    assert not report["extra"]["dns"]["ok"] or \
        report["extra"]["dns"]["err"] != "ok"


def test_dns_resolution_fails(sandbox_checkpoint):
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(
            extra_code=_NET_PROBE.replace("__PORT__", "80")))
    report = _parse(proc)
    dns = report["extra"]["dns"]
    assert not dns["ok"], f"DNS 解析在沙箱内可用: {dns}"


def test_netns_has_no_external_routes(sandbox_checkpoint):
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(
            targets=[("routes", "/proc/net/route"),
                     ("devs", "/proc/net/dev")]))
    report = _parse(proc)
    # /proc 可读(新 procfs),但路由表为空(空 netns)
    t = report["targets"]["routes"]
    assert t["read"]["ok"]
    content_lines = 1  # header
    # 额外解析:直接在 probe 内重新统计非空行
    proc2 = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(
            extra_code='''
try:
    with open("/proc/net/route") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    report["extra"]["route_lines"] = len(lines)
except Exception as e:
    report["extra"]["route_error"] = repr(e)
'''))
    report2 = _parse(proc2)
    assert report2["extra"]["route_lines"] <= content_lines, (
        f"沙箱内存在外部路由: {report2['extra']}")
