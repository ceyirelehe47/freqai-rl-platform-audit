# -*- coding: utf-8 -*-
"""policy v2 — 透传已验 p0policy(B 臂),零自制分布数学。

sample/mode/log_prob 全部透传 P0DistView(arm="B"):
- 随机=dist.sample()(branch bernoulli+mix multinomial+Beta 连续体,
  连续抽样保留,非代表点);
- 确定性=dist.mode()=p0_category_decode(P0CategoryMax-v1)。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_SRC = os.path.abspath(os.path.join(
    _HERE, "..", "freqai-rl-audit", "stage2_7_0", "src"))
for _p in (_REPO_SRC,
           os.path.join(_REPO_SRC,
                        "rl_posctl", "skill_p0")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from rl_posctl.skill_p0.p0policy import (  # noqa: E402
    P0ActorCriticPolicy, P0DistView,
    P0AsymBetaDistribution)

ARM = "B"
# 静态参数(8 输入,pi/vf [128,128] Tanh,B 头):
# actor=18696,value=17793,total=36489(与 p0spec HIDDEN 一致)
STATIC_ACTOR = 18696
STATIC_VALUE = 17793
STATIC_TOTAL = 36489

POLICY_KWARGS = {
    "arm": ARM,
    "net_arch": {"pi": [128, 128], "vf": [128, 128]},
    "activation_fn_name": "tanh"}


def dist_view(dist):
    return P0DistView(dist, ARM)


def sample_actions(dist, deterministic=False):
    return dist_view(dist).get_actions(
        deterministic=deterministic)
