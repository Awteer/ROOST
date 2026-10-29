"""ALNS の部品と本体の確認（小さい問題で速く終わるものだけ）．"""

import json
import random

import pytest

import roost  # noqa: F401
from roost.alns import ALNSConfig, run_alns
from roost.evaluate import evaluate
from roost.initial import _truck_only_f, nearest_neighbor
from roost.milp_io import tmax_case
from roost.moves import (
    Ctx, Move, SearchParams, drone_moves, drop_unused_ncr, merge_same_ncr, remove_customer, truck_moves,
)
from roost.operators import DESTROY, REPAIR, finish
from roost.solution import Loop, Solution, Sortie, Stop
from roost.tables import build_tables


def _prob(mode="5", tmax="inf"):
    row = dict(mode_id=mode, tmax_min=tmax, route=json.dumps(["0"]), sorties="[]", loops="[]")
    prob, opts, _ = tmax_case(row)
    return prob, opts, build_tables(prob)


def _ctx(mode="5", tmax="inf", seed=0):
    prob, opts, T = _prob(mode, tmax)
    return Ctx(prob=prob, T=T, opts=opts, sp=SearchParams(), rng=random.Random(seed))


def test_truck_only_f_matches_evaluator():
    ctx = _ctx("2")
    sol = nearest_neighbor(ctx)
    order = [st.ref for st in sol.stops[1:-1]]
    ev = evaluate(ctx.prob, ctx.T, sol, ctx.opts)
    assert ev.feasible
    assert _truck_only_f(ctx, order) == pytest.approx(ev.energy_kwh, rel=1e-12)


def test_every_move_kind_is_evaluated_consistently():
    """どの種類の手も，適用した解を評価器にかけると形のエラーが出ない（実行可能な候補が少なくとも 1 つある）．"""
    ctx = _ctx("5")
    sol = nearest_neighbor(ctx)
    j = next(st.ref for st in sol.stops if st.kind == "customer" and ctx.loop_order.get(st.ref))
    pool = []
    remove_customer(sol, j, pool)
    ev = ctx.ev(sol)
    moves = truck_moves(sol, j) + drone_moves(ctx, sol, ev, j)
    kinds = {m.kind for m in moves}
    assert {"T", "O", "S", "NO"} <= kinds and kinds & {"NSL", "NSR"}
    feasible_kinds = set()
    for m in moves:
        s = m.apply(sol)
        e = ctx.ev(s)
        if e.feasible:
            feasible_kinds.add(m.kind)
            # 完成した解として評価しても同じ値（新しい NCR はそのまま使われている）
            e2 = evaluate(ctx.prob, ctx.T, s, ctx.opts)
            assert e2.feasible, (m, e2.errors)
            assert e2.energy_kwh == pytest.approx(e.energy_kwh)
    assert {"T", "O", "NO"} <= feasible_kinds


def test_merge_same_ncr_turns_sortie_into_loop():
    stops = [Stop(0, "depot", 0), Stop(1, "ncr", 0), Stop(2, "ncr", 0), Stop(3, "customer", 2), Stop(4, "depot", 0)]
    sol = Solution(stops=stops, drone={1: Sortie(1, 2), 3: Loop(2), 4: Sortie(2, 3)})
    merge_same_ncr(sol)
    assert [st.uid for st in sol.stops] == [0, 1, 3, 4]
    assert sol.drone[1] == Loop(1)
    assert sol.drone[3] == Loop(1)
    assert sol.drone[4] == Sortie(1, 3)


def test_drop_unused_ncr():
    stops = [Stop(0, "depot", 0), Stop(1, "ncr", 0), Stop(2, "customer", 2), Stop(3, "ncr", 0), Stop(4, "depot", 0)]
    sol = Solution(stops=stops, drone={1: Loop(3)})
    drop_unused_ncr(sol)
    assert [st.uid for st in sol.stops] == [0, 2, 3, 4]


def test_remove_anchor_customer_removes_dependents():
    stops = [Stop(0, "depot", 0), Stop(1, "customer", 2), Stop(2, "customer", 5), Stop(3, "depot", 0)]
    sol = Solution(stops=stops, drone={1: Sortie(0, 1), 3: Sortie(1, 2), 4: Loop(1)})
    pool = []
    remove_customer(sol, 2, pool)
    assert sorted(pool) == [1, 2, 3, 4]
    assert [st.uid for st in sol.stops] == [0, 2, 3]
    assert sol.drone == {}


@pytest.mark.parametrize("dn", sorted(DESTROY))
@pytest.mark.parametrize("rn", sorted(REPAIR))
def test_every_operator_pair_gives_complete_feasible_solution(dn, rn):
    ctx = _ctx("5", seed=3)
    res = run_alns(ctx.prob, ctx.T, ctx.opts, ALNSConfig(iterations=5), seed=2)
    sol = res.best.copy()
    pool = DESTROY[dn](ctx, sol, 3)
    sol = finish(ctx, REPAIR[rn](ctx, sol, pool))
    ev = evaluate(ctx.prob, ctx.T, sol, ctx.opts)
    assert ev.feasible, ev.errors


def test_alns_reaches_milp_optimum_small():
    # 8.20.9.a・NCR r0・往復あり・上限なし：MILP の最適値 16.284290832871854
    prob, opts, T = _prob("5")
    res = run_alns(prob, T, opts, ALNSConfig(iterations=300), seed=1)
    assert res.best_eval.feasible
    assert res.best_eval.energy_kwh == pytest.approx(16.284290832871854, rel=1e-9)


def test_alns_respects_tmax():
    prob, opts, T = _prob("5", "70")
    res = run_alns(prob, T, opts, ALNSConfig(iterations=300), seed=1)
    ev = evaluate(prob, T, res.best, opts)
    assert ev.feasible and ev.within_tmax
    assert ev.completion_h <= 70 / 60 + 1e-9


def test_alns_truck_only_mode_uses_no_drone():
    prob, opts, T = _prob("1")
    res = run_alns(prob, T, opts, ALNSConfig(iterations=1000), seed=1)
    assert res.best.drone == {}
    assert res.best_eval.energy_kwh == pytest.approx(29.03103933503166, rel=1e-9)


def test_alns_is_deterministic():
    prob, opts, T = _prob("4")
    a = run_alns(prob, T, opts, ALNSConfig(iterations=150), seed=7)
    b = run_alns(prob, T, opts, ALNSConfig(iterations=150), seed=7)
    assert a.best_eval.energy_kwh == b.best_eval.energy_kwh
    assert [h["cur_kwh"] for h in a.history] == [h["cur_kwh"] for h in b.history]
