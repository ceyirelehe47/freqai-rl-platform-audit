# -*- coding: utf-8 -*-
"""lock_interval — 五点诊断区间只读锁定(不读 V/P@V/积分)。

核对:G017 状态 si=16(state_space 序);t=31/future=V[30];
区间=[-26/128,-25/128](best w=-.2 在均值回报 post 的所在单元,
**事前指定**,非按新结果挑);锁五点 eL,1/4,中,3/4,eR。
"""
import hashlib
import json
import sys

TIER = "/mnt/f/trading/unified_flat_calib_official_attempt2_20261016/tier_L2.json"
TIER_SHA = ("124eb67c5f63cd3cc8fd5dfe"
            "83ac8e71fab54dd1e9077552"
            "02413de0fa3277c7")
V_SHA = ("35ef5480c97508752f16fcddd"
         "0960d82a6e5b38ac950aac45f"
         "c78cf221b40515")
QID, SI, T, TF = "G017", 16, 31, 30
S, C, Q, G = -1, 1, 0.75, 0
MU = S * C * Q * 1.2e-3
SIG = 0.03
W_BEST = -0.2
E_L, E_R = -26.0 / 128.0, -25.0 / 128.0


def states_order():
    return [(s, c, q, g)
            for s in (-1, 0, 1)
            for c in (0, 1)
            for q in (0.0, 0.25, 0.5,
                      0.75, 1.0)
            for g in (0, 1)]


def main(lock_path):
    h = hashlib.sha256()
    with open(TIER, "rb") as f:
        for ch in iter(lambda:
                       f.read(1 << 20),
                       b""):
            h.update(ch)
    assert h.hexdigest() == TIER_SHA
    meta = json.load(
        open(TIER, encoding="utf-8")
    )["tier_meta"]
    acc = [float(x)
           for x in
           meta["accounts"]]
    acts = [float(x)
            for x in
            meta["actions"]]
    st = states_order()
    assert st[SI] == (S, C, Q, G)
    # 端点必须是真实账户结点;取实际索引
    iL = acc.index(E_L)
    iR = acc.index(E_R)
    assert iR == iL + 1, \
        "非相邻单元:%d,%d" % (iL, iR)
    post = (W_BEST * (1 + MU)
            / (1 + W_BEST * MU))
    assert E_L <= post <= E_R, \
        "post %.9f 不在锁区间" % post
    pts = [E_L,
           E_L + 0.25 * (E_R - E_L),
           0.5 * (E_L + E_R),
           E_L + 0.75 * (E_R - E_L),
           E_R]
    lock = {
        "_status": "LOCKED_PREPARED_"
                   "NOT_RUN",
        "qid": QID, "si": SI,
        "state": [S, C, Q, G],
        "t": T, "t_future": TF,
        "mu": MU, "sigma": SIG,
        "w_best_mean": W_BEST,
        "post_at_mean": post,
        "interval": {
            "eL": E_L, "eR": E_R,
            "iL": iL, "iR": iR,
            "expected": [
                -0.203125,
                -0.1953125]},
        "five_points": pts,
        "n_actions": len(acts),
        "n_accounts": len(acc),
        "tier_sha256": TIER_SHA,
        "v_sha256": V_SHA}
    json.dump(lock,
              open(lock_path, "w",
                   encoding="utf-8"),
              indent=1,
              allow_nan=False)
    print("LOCKED si=%d t=%d "
          "iL=%d iR=%d post=%.9f "
          "pts=%s nA=%d nAcc=%d"
          % (SI, T, iL, iR, post,
             pts, len(acts),
             len(acc)))


if __name__ == "__main__":
    main(sys.argv[1]
         if len(sys.argv) > 1
         else "LOCK_FIVEPOINT"
              ".json")
