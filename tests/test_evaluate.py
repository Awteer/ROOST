"""評価器 v1 の確認．

1. MILP の最適解（8.20.9.a，NCR r0，tmax_sweep の結果）を直して評価し，MILP の値と一致すること
2. 形のチェック・同期の違反を 1 つずつ作り，評価器が必ず見つけること
"""

from dataclasses import replace

import pytest

import roost  # noqa: F401
from roost.evaluate import evaluate
from roost.milp_io import TMAX_MODES, solution_from_labels, tmax_case
from roost.solution import Loop, Solution, Sortie, Stop
from roost.tables import build_tables

# NCR_MILP results/tmax_8.20.9.a/sweep.csv から抜き出した行（mode_id, T_max, 目的の値, 完了 [分], 待ち [分], 経路）
MILP_ROWS = [
    (1, "inf", 29.03103933503166, 88.02735127406329, 0.0,
     ["0", "c3", "c4", "c8", "c5", "c2", "c7", "c6", "c1", "0'"], [], []),
    (2, "inf", 25.160863422294288, 76.79942050103617, 11.462179636954982,
     ["0", "c2", "c5", "c7", "c6", "c1", "0'"], [["0", "c4", "c2"], ["c1", "c3", "0'"], ["c2", "c8", "c5"]], []),
    (3, "inf", 19.229613406257293, 95.75059496880475, 14.378148699499436,
     ["0", "c2", "c7", "c5", "0'"], [],
     [["0", "c1"], ["0", "c3"], ["0", "c4"], ["c5", "c8"], ["c7", "c6"]]),
    (4, "inf", 20.071162759547942, 73.5789263531231, 33.73404443281078,
     ["0", "r0", "c2", "c8", "c5", "0'"],
     [["0", "c1", "r0"], ["c2", "c7", "c8"], ["c5", "c4", "0'"], ["c8", "c3", "c5"], ["r0", "c6", "c2"]], []),
    (5, "inf", 16.284290832871854, 93.32257723126551, 38.16883999260869,
     ["0", "r0", "c2", "c5", "0'"], [],
     [["0", "c3"], ["0", "c4"], ["c5", "c8"], ["r0", "c1"], ["r0", "c6"], ["r0", "c7"]]),
    (5, "70", 16.82755137346548, 68.68407533105405, 25.45076182066732,
     ["0", "c5", "c2", "r0", "0'"], [["0", "c4", "c5"], ["c2", "c7", "r0"], ["c5", "c8", "c2"], ["r0", "c1", "0'"]],
     [["0", "c3"], ["r0", "c6"]]),
]


def _case(mode, tmax, route, sorties, loops):
    import json
    row = dict(mode_id=str(mode), tmax_min=tmax, route=json.dumps(route), sorties=json.dumps(sorties),
               loops=json.dumps(loops))
    return tmax_case(row)


@pytest.mark.parametrize("mode,tmax,obj,comp_min,wait_min,route,sorties,loops", MILP_ROWS)
def test_matches_milp_optimum(mode, tmax, obj, comp_min, wait_min, route, sorties, loops):
    prob, opts, sol = _case(mode, tmax, route, sorties, loops)
    ev = evaluate(prob, build_tables(prob), sol, opts)
    assert ev.feasible, ev.errors
    assert ev.within_tmax
    assert ev.energy_kwh == pytest.approx(obj, rel=1e-9)
    assert ev.completion_h * 60 == pytest.approx(comp_min, rel=1e-9)
    assert ev.wait_h * 60 == pytest.approx(wait_min, rel=1e-9, abs=1e-9)


# ---------------------------------------------------------------------------
# 違反を作って見つけられるか（基準は (4) NCR あり・往復なし・上限なしの最適解に，往復を許した設定）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def base():
    _mode, tmax, _o, _c, _w, route, sorties, loops = MILP_ROWS[3]
    prob, opts, sol = _case(4, tmax, route, sorties, loops)
    opts = replace(opts, allow_loops=True, depot_loops=True)
    T = build_tables(prob)
    ev = evaluate(prob, T, sol, opts)
    assert ev.feasible, ev.errors
    return prob, opts, sol, T


def _errors(base, sol, **opt_changes):
    prob, opts, _sol, T = base
    ev = evaluate(prob, T, sol, replace(opts, **opt_changes))
    assert not ev.feasible
    return " | ".join(ev.errors)


def test_overlap_detected(base):
    _p, _o, sol, _T = base
    s = sol.copy()
    # 経路 0(0) r0(1) c2(2) c8(3) c5(4) 0'(5)．c6 は r0→c2，c7 は c2→c8．c6 を r0→c8 に伸ばすと c7 と重なる
    s.drone[6] = Sortie(launch=1, retrieve=3)
    assert "overlap" in _errors(base, s)


def test_loop_inside_sortie_detected(base):
    _p, _o, sol, _T = base
    s = sol.copy()
    # c7 は c2(2)→c8(3)．c3（c8→c5）を c2→c5 に伸ばしたうえで，c7 を c8 での往復にすると，c8 は飛行中
    s.drone[3] = Sortie(launch=2, retrieve=4)
    s.drone[7] = Loop(at=3)
    msg = _errors(base, s)
    assert "N30" in msg


def test_unused_ncr_detected(base):
    _p, _o, sol, _T = base
    s = sol.copy()
    # r0 で回収・発射している c1・c6 を，r0 を使わない形に替える
    s.drone[1] = Sortie(launch=0, retrieve=2)
    del s.drone[6]
    s.stops.insert(3, Stop(uid=9, kind="customer", ref=6))
    s.drone[7] = Sortie(launch=9, retrieve=3)
    assert "N18" in _errors(base, s)


def test_consecutive_same_ncr_detected(base):
    prob, _o, sol, _T = base
    s = sol.copy()
    s.stops.insert(2, Stop(uid=10, kind="ncr", ref=0))
    s.drone[6] = Sortie(launch=10, retrieve=2)
    msg = _errors(base, s, max_visits=None)
    assert "N7" in msg


def test_max_visits_detected(base):
    _p, _o, sol, _T = base
    s = sol.copy()
    s.stops.insert(4, Stop(uid=11, kind="ncr", ref=0))   # c8 の後にもう一度 r0
    s.drone[3] = Sortie(launch=3, retrieve=11)
    s.drone[4] = Sortie(launch=11, retrieve=5)
    s.stops.insert(5, Stop(uid=12, kind="customer", ref=5))  # 形を保つための調整はしない：上限の違反だけを見る
    msg = _errors(base, s, max_visits=1)
    assert "A4" in msg


def test_depot_to_depot_sortie_detected(base):
    _p, _o, sol, _T = base
    s = sol.copy()
    s.drone[4] = Sortie(launch=0, retrieve=5)
    assert "A9" in _errors(base, s)


def test_loop_at_end_depot_detected(base):
    _p, _o, sol, _T = base
    s = sol.copy()
    s.drone[4] = Loop(at=5)
    assert "#17" in _errors(base, s)


def test_heavy_customer_by_drone_detected(base):
    prob, _o, sol, T = base
    heavy = [j for j in range(1, prob.n + 1) if not T.drone_ok[j]]
    assert heavy
    s = sol.copy()
    j = heavy[0]
    s.stops = [st for st in s.stops if not (st.kind == "customer" and st.ref == j)]
    s.drone[j] = Loop(at=0)
    assert "too heavy" in _errors(base, s)


def test_customer_twice_detected(base):
    _p, _o, sol, _T = base
    s = sol.copy()
    s.stops.insert(1, Stop(uid=20, kind="customer", ref=1))   # c1 はドローンでも配っている
    assert "served 2 times" in _errors(base, s)


def test_drone_early_detected():
    # (2) NCR なし・往復なし・上限なしの最適解で，c4（0→c2）の回収を c2 → c5 にずらすと
    # ドローンが c5 に先に着くか．着かない場合もあるので，トラックの区間が長い組を探して確かめる
    _mode, tmax, _o, _c, _w, route, sorties, loops = MILP_ROWS[1]
    prob, opts, sol = _case(2, tmax, route, sorties, loops)
    T = build_tables(prob)
    # 0(0) c2(1) c5(2) c7(3) c6(4) c1(5) 0'(6)．c8 は c2→c5．発射を 0 にして回収を 0' まで伸ばす代わりに，
    # ドローンだけで遠回りしない組：c3（c1→0'）を c5→c6 にすれば，トラックは c5→c7→c6，ドローンは c5→c3→c6
    s = sol.copy()
    s.drone[3] = Sortie(launch=2, retrieve=4)
    ev = evaluate(prob, T, s, opts)
    early = any("before the truck" in e for e in ev.errors)
    t_truck = T.tau[5][7] + T.tau[7][6]
    t_drone = T.trip(5, 3, 6)[1]
    assert early == (t_drone < t_truck)
    ev2 = evaluate(prob, T, s, replace(opts, forbid_drone_early=False))
    assert not any("before the truck" in e for e in ev2.errors)


def test_capacity_detected(base):
    prob, opts, sol, T = base
    s = sol.copy()
    T2 = build_tables(prob)
    T2.Q_t = 10.0
    ev = evaluate(prob, T2, s, opts)
    assert not ev.feasible and any("capacity" in e for e in ev.errors)


def test_battery_detected(base):
    prob, opts, sol, _T = base
    T2 = build_tables(prob)
    T2.cap_b = 0.01
    ev = evaluate(prob, T2, sol, opts)
    assert not ev.feasible and any("battery" in e for e in ev.errors)


def test_tmax_penalty(base):
    prob, opts, sol, T = base
    ev0 = evaluate(prob, T, sol, opts)
    ev = evaluate(prob, T, sol, replace(opts, tmax_h=ev0.completion_h - 0.1, lam_kwh_per_h=5.0))
    assert ev.feasible                      # 形は正しい
    assert not ev.within_tmax
    assert ev.tmax_excess_h == pytest.approx(0.1)
    assert ev.objective == pytest.approx(ev0.energy_kwh + 0.5)


def test_truck_does_not_move():
    # 全員をデポからの往復で配る解（トラックは出発しない）．route ["0"] の扱い
    prob, opts, _sol = _case(5, "inf", ["0", "0'"], [], [])
    T = build_tables(prob)
    light = [j for j in range(1, prob.n + 1) if T.drone_ok[j]]
    heavy = [j for j in range(1, prob.n + 1) if not T.drone_ok[j]]
    sol = solution_from_labels(["0"], [], [["0", f"c{j}"] for j in light])
    ev = evaluate(prob, T, sol, opts)
    if heavy:
        assert not ev.feasible   # 重い客が配られていない
    assert ev.truck_kwh == 0.0
    assert ev.completion_h == pytest.approx(sum(T.trip(0, j, 0)[1] for j in light))


def test_modes_cover_all():
    assert sorted(TMAX_MODES) == [1, 2, 3, 4, 5]


def test_solution_from_labels_uids():
    sol = solution_from_labels(["0", "c2", "r0", "0'"], [["0", "c1", "r0"]], [["r0", "c3"]])
    assert [st.uid for st in sol.stops] == [0, 1, 2, 3]
    assert sol.drone[1] == Sortie(launch=0, retrieve=2)
    assert sol.drone[3] == Loop(at=2)
    assert isinstance(sol, Solution)
