#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M01:有限离散分布条件化与 first_pass 公式的穷举核验(WP2 数学勘误)。

不做任何 Monte Carlo、不调 C3 生成器:在 8 结果有限空间上按
first_pass 的真实样本空间(截断前缀)穷举——通过前缀 x_1..x_k
(x_1..x_{k-1}∉S 且 x_k∈S,k≤m)与失败前缀(长度 m 全∉S)构成划分
——逐项验证任务书 §4 的公式,并给出错误 1/q 示例的数值差与 D0
实际参数的正确归一化因子。

输出: JSON 报告(可选 --out 落盘;stdout 打印)。
"""
from __future__ import annotations

import json
import sys
import time
from itertools import product

# 有限样本空间(8 结果,概率和=1;非退化选取)
P = [0.10, 0.20, 0.05, 0.15, 0.10, 0.20, 0.10, 0.10]
N = len(P)
S = frozenset({1, 2, 3, 4, 5})   # 全部结构条件通过
D = frozenset({2, 3, 4, 5, 6})   # 至少一个 distractor 对
A = frozenset({1, 2, 3})         # 目标事件(与 S/D 部分相交)
M = 5                            # first_pass 最多尝试次数

# D0 实际参数(上轮 DP:零 distractor 概率与五连独立模型值)
D0_Q = 0.21153571482930775
D0_Q5 = 0.00042356348415488205


def p_of(ev: frozenset) -> float:
    return sum(P[i] for i in ev)


def _weight(seq) -> float:
    w = 1.0
    for x in seq:
        w *= P[x]
    return w


def exhaustive_first_pass():
    """穷举截断前缀样本空间。

    返回 (总测度, P(J≤m), P(X_J∈A 且 J≤m), {i: P(X_J=i | J≤m) 穷举分子})。
    """
    w_total = 0.0
    w_pass = 0.0
    w_pass_a = 0.0
    per_value = {i: 0.0 for i in range(N)}
    # 通过前缀:前 k-1 个候选 ∉S,第 k 个 ∈S
    for k in range(1, M + 1):
        for seq in product(range(N), repeat=k):
            if seq[-1] not in S or any(x in S for x in seq[:-1]):
                continue
            w = _weight(seq)
            w_total += w
            w_pass += w
            per_value[seq[-1]] += w
            if seq[-1] in A:
                w_pass_a += w
    # 失败前缀:长度 m 全 ∉S
    for seq in product(range(N), repeat=M):
        if any(x in S for x in seq):
            continue
        w_total += _weight(seq)
    return w_total, w_pass, w_pass_a, per_value


def main() -> int:
    q = 1.0 - p_of(D)             # P(D 的补集) = P(零 distractor)
    p_s = p_of(S)
    rows: dict = {
        "format": "r17rdd-m01-finite-exhaustive-v1",
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime()),
        "space": {"n_outcomes": N, "probabilities": P,
                  "S": sorted(S), "D": sorted(D), "A": sorted(A),
                  "m": M,
                  "n_enumerated_prefixes": sum(N ** k for k in
                                               range(1, M + 1))},
        "checks": {},
    }
    ok = True

    def check(name: str, cond: bool, detail: dict) -> None:
        nonlocal ok
        rows["checks"][name] = {"ok": bool(cond), **detail}
        ok = ok and bool(cond)

    # 1) 条件概率:分母是 1-q(=P(≥1 对 distractor)),不是 q
    num = p_of(A & D)
    correct = num / (1 - q)
    wrong = num / q
    got = sum(P[i] for i in A & D) / sum(P[i] for i in D)
    check("conditioning_on_D", abs(correct - got) < 1e-12, {
        "formula": "P(X∈A|D)=P(A∩D)/(1-q)", "q": q,
        "1_over_1_minus_q": 1.0 / (1.0 - q),
        "value": correct, "exhaustive_value": got,
        "wrong_1_over_q_value": wrong,
        "wrong_minus_correct": wrong - correct,
    })
    # 2) 条件分布归一化(在 D 上按 1/(1-q) 缩放)
    cond_sum = sum(P[i] / (1 - q) for i in D)
    check("conditional_normalization", abs(cond_sum - 1.0) < 1e-12, {
        "sum_over_D_scaled": cond_sum})

    # 3) first_pass 穷举 vs 公式
    w_total, w_pass, w_pass_a, per_value = exhaustive_first_pass()
    want_pass = 1 - (1 - p_s) ** M
    want_joint = sum((1 - p_s) ** j * p_of(A & S)
                     for j in range(M))
    check("first_pass_partition_measure", abs(w_total - 1.0) < 1e-9, {
        "exhaustive_total_measure": w_total})
    check("first_pass_P_J_le_m", abs(w_pass - want_pass) < 1e-12, {
        "exhaustive": w_pass, "formula_1_minus_1p_pow_m": want_pass})
    check("first_pass_joint", abs(w_pass_a - want_joint) < 1e-12, {
        "exhaustive": w_pass_a,
        "formula_sum_j_1p_j_minus_1_PAS": want_joint})
    check("first_pass_conditional_output", abs(
        w_pass_a / w_pass - p_of(A & S) / p_s) < 1e-12, {
        "exhaustive": w_pass_a / w_pass,
        "formula_P_AS_over_p": p_of(A & S) / p_s})
    # 4) 成功输出分布逐值 = P(X|S)
    per_value_ok = all(
        abs(per_value[i] / w_pass - P[i] / p_s) < 1e-12 for i in S)
    per_value_ok = per_value_ok and all(
        per_value[i] == 0.0 for i in range(N) if i not in S)
    check("success_output_is_P_given_S", per_value_ok, {
        "exhaustive_per_value_conditional": {
            i: per_value[i] / w_pass for i in sorted(S)},
        "formula_P_given_S": {i: P[i] / p_s for i in sorted(S)},
        "outside_S_all_zero": True})

    # 5) 边界解释(不做除零计算,只记录语义)
    rows["boundaries"] = {
        "p_equals_0": "S 为空 → P(J≤m)=0,成功条件分布未定义"
                      "(不能写 0/0;任何'必然输出'论断非法)",
        "p_equals_1": "S 为全空间 → J=1 恒成立,"
                      "P(X_J∈A|J≤m)=P(A∩S)/p=P(A)",
    }

    # 6) D0 实际参数口径(勘误的数值展示;非有限例子)
    rows["d0_reference"] = {
        "q_zero_distractor": D0_Q,
        "q_pow_5_independent_model": D0_Q5,
        "correct_renormalization_1_over_1_minus_q":
            1.0 / (1.0 - D0_Q),
        "wrong_1_over_q": 1.0 / D0_Q,
        "note": ("条件化在 ≥1 对 distractor(D 的补事件)上,分母 "
                 "1-q≈0.7885;旧报告 §6.3 写 1/q 是对'零 distractor'"
                 "事件错误归一,数值相差约 3.73 倍"),
    }
    rows["verdict"] = "PASS" if ok else "FAIL"
    text = json.dumps(rows, ensure_ascii=False, indent=1)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(text + "\n")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
