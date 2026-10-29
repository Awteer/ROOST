"""初期解（Sacramento 2019 §4.1 の 3 段）．

1. 最近傍：デポから，まだ行っていない客のうちトラックの距離が一番近い客へ進む（全員トラック）
2. 文字列の付け替え：長さ 1〜3 の連続した客の列を，向きをそのまま／逆にして別の位置へ移す．
   良くなる手が見つかったらすぐ移し，良くなる手がなくなるまで繰り返す（トラックだけの解で行う．
   1 台なので Sacramento の「別のルートへの移動」はない）
3. ドローンの追加：トラックの客のうちドローンで運べる客を 1 人ずつ抜き，ドローンでの一番良い配り方
   （既存の停車からの出撃・往復，新しい NCR の停車からの往復・出撃）を探す．一番得をするものを 1 つ足す，を
   得がなくなるまで繰り返す
"""

from __future__ import annotations

import math

from .moves import Ctx, best_move, drone_moves, is_anchor
from .solution import Solution, Stop


def nearest_neighbor(ctx: Ctx) -> Solution:
    prob, T = ctx.prob, ctx.T
    left = set(range(1, prob.n + 1))
    stops = [Stop(uid=0, kind="depot", ref=0)]
    cur = 0
    uid = 1
    while left:
        j = min(left, key=lambda c: (T.dist[cur][c], c))
        stops.append(Stop(uid=uid, kind="customer", ref=j))
        uid += 1
        left.discard(j)
        cur = j
    stops.append(Stop(uid=uid, kind="depot", ref=0))
    return Solution(stops=stops, drone={})


def _truck_only_f(ctx: Ctx, order: list[int]) -> float:
    """トラックだけの解（客の順 order）の目的 f．評価器と同じ式を，形のチェックなしで速く計算する．"""
    prob, T, opts = ctx.prob, ctx.T, ctx.opts
    load = sum(prob.demand(j) for j in order)
    if load > T.Q_t + opts.tol:
        return math.inf
    m_d = T.m_d_kg if opts.include_drone_mass else 0.0
    e = 0.0
    t = 0.0
    prev = 0
    for j in order + [0]:
        e += T.truck_energy(prev, j, load + m_d)
        t += T.tau[prev][j]
        if j:
            load -= prob.demand(j)
        prev = j
    excess = 0.0 if opts.tmax_h is None else max(0.0, t - opts.tmax_h)
    return e + ctx.lam * excess


def string_relocation(ctx: Ctx, sol: Solution, max_rounds: int = 500) -> Solution:
    """長さ 1〜3 の客の列を別の位置へ（向きはそのままと逆の両方）．トラックだけの解に使う．"""
    order = [st.ref for st in sol.stops[1:-1]]
    f_cur = _truck_only_f(ctx, order)
    for _ in range(max_rounds):
        improved = False
        m = len(order)
        for length in (1, 2, 3):
            for i in range(0, m - length + 1):
                seg = order[i:i + length]
                rest = order[:i] + order[i + length:]
                for k in range(0, len(rest) + 1):
                    if k == i:
                        continue
                    for rev in (False, True):
                        if rev and length == 1:
                            continue
                        piece = list(reversed(seg)) if rev else seg
                        cand = rest[:k] + piece + rest[k:]
                        fv = _truck_only_f(ctx, cand)
                        if fv < f_cur - 1e-12:
                            order, f_cur, improved = cand, fv, True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
        if not improved:
            break
    stops = [sol.stops[0]] + [Stop(uid=p + 1, kind="customer", ref=j) for p, j in enumerate(order)]
    stops.append(Stop(uid=len(order) + 1, kind="depot", ref=0))
    return Solution(stops=stops, drone={})


def add_drones(ctx: Ctx, sol: Solution, with_ncr: bool = True) -> Solution:
    """得がなくなるまで，一番得をするドローンの配り方を 1 つずつ足す．with_ncr=False なら新しい NCR の停車は開けない．"""
    while True:
        f_cur = ctx.f(ctx.ev(sol))
        best_s, best_f = None, f_cur - 1e-12
        for st in list(sol.stops):
            if st.kind != "customer" or not ctx.T.drone_ok[st.ref] or is_anchor(sol, st.uid):
                continue
            j = st.ref
            s_wo = sol.copy()
            s_wo.stops = [s for s in s_wo.stops if s.uid != st.uid]
            mv, fv, s_new = best_move(ctx, s_wo, drone_moves(ctx, s_wo, ctx.ev(s_wo), j, with_ncr=with_ncr))
            if s_new is not None and fv < best_f:
                best_s, best_f = s_new, fv
        if best_s is None:
            return sol
        sol = best_s


def build_initial(ctx: Ctx) -> Solution:
    sol = nearest_neighbor(ctx)
    sol = string_relocation(ctx, sol)
    sol = add_drones(ctx, sol)
    return sol
