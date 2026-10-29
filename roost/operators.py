"""壊すオペレータ 5 つと直すオペレータ 4 つ（docs/DESIGN_20261029.md）．

壊す（重みを適応させる）
  random      ：客を β 人抜く（Sacramento 2019 §4.2.1）
  cluster     ：起点の客から近い 2 人のどちらかを抜く，を繰り返す（§4.2.2）
  ncr_open    ：今のトラック経路から距離 D 以内の NCR の候補を一様に選び，その近く（往復のエネルギーで測る）の
                軽い客を β 人抜いて，その候補を空の停車として置く
  ncr_close   ：使っている NCR の停車を消し，そこを使っていた客を抜く．足りなければ近くの客を足して β 人
  ncr_move    ：閉鎖と同じに抜き，近くの候補を空の停車として置く
直す（重みを適応させる．どれもドローンの手に「既存の停車からの往復」「新しい NCR の停車」を含む）
  greedy_tfss ：全員をトラックに最良挿入 → 入れた客を 1 人ずつ，得ならドローンに替える（§4.3.1）
  nearby_tfss ：近くの挿入位置から乱数で選ぶ → 直す前より 10% 以上悪くならない手から乱数で替える（§4.3.2）
  closest     ：トラック・ドローンの全部の手の中で一番安い所に直接入れる（§4.3.3．1 台なので経路は 1 本）
  heavy       ：ドローンで運べない客を先にトラックに入れ，残りを closest で入れる（§4.3.4）

Sacramento との違い
  * TF-SS の第 2 段で替える候補は既定で解のトラックの客の全員（Sacramento どおり）．
    大規模で重すぎるときは SearchParams.phase2_scope="inserted" で直した客だけに絞れる（Xiao 2024 の IALNS と同じ）
  * 直したあとに誰も使わない NCR の停車を消す（決定 #9）
"""

from __future__ import annotations

import math

from .moves import (
    Ctx, Move, best_move, cheapest_ncr_position, drone_moves, drop_unused_ncr, insert_stop, insert_truck_fallback,
    is_anchor, merge_same_ncr, remove_customer, remove_stop, scored_moves, truck_moves, users_of,
)
from .solution import Solution, Stop

# ---------------------------------------------------------------------------
# 壊す
# ---------------------------------------------------------------------------


def removal_count(ctx: Ctx) -> int:
    sp = ctx.sp
    c_low = ctx.rng.randint(*sp.c_low_range)
    return max(1, min(max(c_low, int(round(sp.kappa * ctx.prob.n))), sp.c_lim, ctx.prob.n))


def customers_in(sol: Solution) -> list[int]:
    return sorted([st.ref for st in sol.stops if st.kind == "customer"] + list(sol.drone))


def destroy_random(ctx: Ctx, sol: Solution, beta: int) -> list[int]:
    pool: list[int] = []
    while len(pool) < beta:
        cs = customers_in(sol)
        if not cs:
            break
        remove_customer(sol, ctx.rng.choice(cs), pool)
    merge_same_ncr(sol)
    return pool


def destroy_cluster(ctx: Ctx, sol: Solution, beta: int) -> list[int]:
    pool: list[int] = []
    cs = customers_in(sol)
    if not cs:
        return pool
    c1 = ctx.rng.choice(cs)
    remove_customer(sol, c1, pool)
    D = ctx.T.dist
    while len(pool) < beta:
        cs = customers_in(sol)
        if not cs:
            break
        cs.sort(key=lambda c: (D[c1][c], c))
        remove_customer(sol, ctx.rng.choice(cs[:2]), pool)
    merge_same_ncr(sol)
    return pool


def _remove_near_loop(ctx: Ctx, sol: Solution, r_loc: int, beta: int, pool: list[int]) -> None:
    """地点 r_loc からの往復のエネルギーが小さい順に，ドローンで運べる客を抜いて pool を β 人にする．"""
    T = ctx.T
    cand = []
    for c in customers_in(sol):
        if T.drone_ok[c] and c not in pool:
            e, _ = T.trip(r_loc, c, r_loc) if r_loc != c else (0.0, 0.0)
            cand.append((e, c))
    cand.sort()
    for _, c in cand:
        if len(pool) >= beta:
            break
        if c in customers_in(sol):
            remove_customer(sol, c, pool)


def _place_empty_ncr(ctx: Ctx, sol: Solution, ell: int) -> bool:
    ev = ctx.ev(sol)
    p = cheapest_ncr_position(ctx, sol, ev, ell)
    if p is None:
        return False
    insert_stop(sol, p, Stop(uid=sol.next_uid(), kind="ncr", ref=ell))
    return True


def destroy_ncr_open(ctx: Ctx, sol: Solution, beta: int) -> list[int]:
    prob, T = ctx.prob, ctx.T
    if prob.n_ncr == 0:
        return destroy_random(ctx, sol, beta)
    route_locs = [ctx.loc(st) for st in sol.stops]
    D = ctx.sp.ncr_open_radius_km
    cands = []
    for ell in range(prob.n_ncr):
        r = prob.ncr_loc(ell)
        if ctx.opts.max_visits is not None and sum(1 for st in sol.stops if st.kind == "ncr" and st.ref == ell) \
                >= ctx.opts.max_visits:
            continue
        if min(T.dist[a][r] for a in route_locs) <= D:
            cands.append(ell)
    if not cands:
        return destroy_random(ctx, sol, beta)
    ell = ctx.rng.choice(cands)
    pool: list[int] = []
    _remove_near_loop(ctx, sol, prob.ncr_loc(ell), beta, pool)
    merge_same_ncr(sol)
    _place_empty_ncr(ctx, sol, ell)
    return pool


def _close_one(ctx: Ctx, sol: Solution, beta: int) -> tuple[list[int], int] | None:
    ncr_stops = [st for st in sol.stops if st.kind == "ncr"]
    if not ncr_stops:
        return None
    st = ctx.rng.choice(ncr_stops)
    pool: list[int] = []
    remove_stop(sol, st.uid, pool)
    _remove_near_loop(ctx, sol, ctx.prob.ncr_loc(st.ref), beta, pool)
    merge_same_ncr(sol)
    return pool, st.ref


def destroy_ncr_close(ctx: Ctx, sol: Solution, beta: int) -> list[int]:
    res = _close_one(ctx, sol, beta)
    if res is None:
        return destroy_random(ctx, sol, beta)
    return res[0]


def destroy_ncr_move(ctx: Ctx, sol: Solution, beta: int) -> list[int]:
    res = _close_one(ctx, sol, beta)
    if res is None:
        return destroy_random(ctx, sol, beta)
    pool, ell = res
    near = ctx.near_ncr.get(ell, [])[: ctx.sp.ncr_move_k]
    if near:
        _place_empty_ncr(ctx, sol, ctx.rng.choice(near))
    return pool


DESTROY = {
    "random": destroy_random,
    "cluster": destroy_cluster,
    "ncr_open": destroy_ncr_open,
    "ncr_close": destroy_ncr_close,
    "ncr_move": destroy_ncr_move,
}

# ---------------------------------------------------------------------------
# 直す
# ---------------------------------------------------------------------------


def _truck_insert_best(ctx: Ctx, sol: Solution, j: int, pool: list[int], positions=None) -> Solution:
    mv, fv, s = best_move(ctx, sol, truck_moves(sol, j, positions))
    if s is None and positions is not None:
        mv, fv, s = best_move(ctx, sol, truck_moves(sol, j))
    if s is None:
        s = insert_truck_fallback(ctx, sol, j, pool)
    return s


def _phase2(ctx: Ctx, sol: Solution, targets: list[int], randomized: bool) -> Solution:
    """TF-SS の第 2 段：トラックの客 j（発射・回収・往復がない停車）をドローンに替えて得なら替える．

    候補は SearchParams.phase2_scope が "all" なら解のトラックの客の全員（Sacramento どおり），
    "inserted" なら直した客だけ（targets）．
    """
    if ctx.sp.phase2_scope == "all":
        targets = [st.ref for st in sol.stops if st.kind == "customer"]
    order = list(targets)
    ctx.rng.shuffle(order)
    for j in order:
        if not ctx.T.drone_ok[j]:
            continue
        st = next((s for s in sol.stops if s.kind == "customer" and s.ref == j), None)
        if st is None or is_anchor(sol, st.uid):
            continue
        eta = ctx.f(ctx.ev(sol))
        s_wo = sol.copy()
        s_wo.stops = [s for s in s_wo.stops if s.uid != st.uid]
        ev_wo = ctx.ev(s_wo)
        moves = drone_moves(ctx, s_wo, ev_wo, j)
        if not randomized:
            mv, fv, s_new = best_move(ctx, s_wo, moves)
            if s_new is not None and fv < eta - 1e-12:
                sol = s_new
        else:
            ok = [(fv, mv, s) for (fv, mv, s) in scored_moves(ctx, s_wo, moves) if fv <= (1.0 + ctx.sp.nearby_slack) * eta]
            if ok:
                sol = ctx.rng.choice(ok)[2]
    return sol


def repair_greedy_tfss(ctx: Ctx, sol: Solution, pool: list[int]) -> Solution:
    queue = list(pool)
    ctx.rng.shuffle(queue)
    inserted = []
    guard = 0
    while queue:
        j = queue.pop()
        before = len(queue)
        sol = _truck_insert_best(ctx, sol, j, queue)
        if len(queue) > before:
            guard += 1
            if guard > ctx.sp.max_fallback:
                raise RuntimeError("too many fallbacks in truck insertion")
        inserted.append(j)
    return _phase2(ctx, sol, inserted, randomized=False)


def repair_nearby_tfss(ctx: Ctx, sol: Solution, pool: list[int]) -> Solution:
    queue = list(pool)
    ctx.rng.shuffle(queue)
    inserted = []
    R = ctx.sp.nearby_radius_km
    guard = 0
    while queue:
        j = queue.pop()
        locs = [ctx.loc(st) for st in sol.stops]
        near = [p for p in range(1, len(sol.stops))
                if ctx.T.dist[locs[p - 1]][j] <= R or ctx.T.dist[locs[p]][j] <= R]
        cands = scored_moves(ctx, sol, truck_moves(sol, j, near)) if near else []
        before = len(queue)
        if cands:
            sol = ctx.rng.choice(cands)[2]
        else:
            sol = _truck_insert_best(ctx, sol, j, queue)
        if len(queue) > before:
            guard += 1
            if guard > ctx.sp.max_fallback:
                raise RuntimeError("too many fallbacks in truck insertion")
        inserted.append(j)
    return _phase2(ctx, sol, inserted, randomized=True)


def _closest_insert(ctx: Ctx, sol: Solution, js: list[int]) -> tuple[Solution, list[int]]:
    """全部の手（トラック・ドローン・新しい NCR）の中で一番安い所に入れる．入れられなかった客を返す．"""
    left = []
    order = list(js)
    ctx.rng.shuffle(order)
    for j in order:
        ev = ctx.ev(sol)
        moves = truck_moves(sol, j) + drone_moves(ctx, sol, ev, j)
        mv, fv, s = best_move(ctx, sol, moves)
        if s is None:
            left.append(j)
        else:
            sol = s
    return sol, left


def repair_closest(ctx: Ctx, sol: Solution, pool: list[int]) -> Solution:
    sol, left = _closest_insert(ctx, sol, pool)
    if left:
        sol = repair_greedy_tfss(ctx, sol, left)
    return sol


def repair_heavy(ctx: Ctx, sol: Solution, pool: list[int]) -> Solution:
    heavy = [j for j in pool if not ctx.T.drone_ok[j]]
    light = [j for j in pool if ctx.T.drone_ok[j]]
    queue = list(heavy)
    ctx.rng.shuffle(queue)
    guard = 0
    while queue:
        j = queue.pop()
        before = len(queue)
        sol = _truck_insert_best(ctx, sol, j, queue)
        if len(queue) > before:
            light.extend(queue[before:])   # 逃げ道で抜けたドローン客は軽い客の側で入れ直す
            del queue[before:]
            guard += 1
            if guard > ctx.sp.max_fallback:
                raise RuntimeError("too many fallbacks in truck insertion")
    return repair_closest(ctx, sol, light)


REPAIR = {
    "greedy_tfss": repair_greedy_tfss,
    "nearby_tfss": repair_nearby_tfss,
    "closest": repair_closest,
    "heavy": repair_heavy,
}


def finish(ctx: Ctx, sol: Solution) -> Solution:
    """直した後の後始末：誰も使わない NCR の停車を消す（(N18)）．"""
    s = sol.copy()
    drop_unused_ncr(s)
    return s
