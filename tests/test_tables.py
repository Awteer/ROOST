"""表の値が xiao/energy.py の関数を直接呼んだ値と一致するか（評価器が表を使うので，その土台の確認）．"""

import math
import random

import pytest

import roost  # noqa: F401  （XIAO を import できるようにする）
from xiao import energy as E
from xiao.params import EnergyParams

from roost.milp_io import xiao_instance
from roost.problem import Point, from_xiao
from roost.tables import build_tables, geometry


@pytest.fixture(scope="module")
def setup():
    xi = xiao_instance("8.20.9.a")
    prob = from_xiao(xi, (Point(-10.0 / 3.0, 10.0 / 3.0, 1.0), Point(2.0, -1.0, 40.0)))
    return prob, build_tables(prob)


def test_truck_energy_matches_energy_py(setup):
    prob, T = setup
    tp = EnergyParams().truck
    rng = random.Random(0)
    for a in range(prob.n_locations):
        for b in range(prob.n_locations):
            for _ in range(3):
                w = rng.uniform(0.0, 325.0)   # 積荷＋機体の範囲
                d, al = geometry(prob.point(a), prob.point(b))
                ref = E.truck_arc_energy_kwh(d, al, w, tp)
                assert T.truck_energy(a, b, w) == pytest.approx(ref, rel=1e-12, abs=1e-12)


def test_drone_trip_matches_energy_py(setup):
    prob, T = setup
    dp = EnergyParams().drone
    for j in range(1, prob.n + 1):
        if not T.drone_ok[j]:
            assert prob.demand(j) > dp.max_payload_kg
            continue
        for a in range(prob.n_locations):
            for b in range(prob.n_locations):
                if a == j or b == j:
                    continue
                d1, a1 = geometry(prob.point(a), prob.point(j))
                d2, a2 = geometry(prob.point(j), prob.point(b))
                e_ref = E.drone_trip_energy_kwh(d1, a1, d2, a2, prob.demand(j), dp)
                t_ref = E.drone_trip_time_h(d1, d2, dp)
                e, t = T.trip(a, j, b)
                assert e == pytest.approx(e_ref, rel=1e-12)
                assert t == pytest.approx(t_ref, rel=1e-12)


def test_same_point_is_zero(setup):
    prob, T = setup
    assert T.truck_energy(0, 0, 100.0) == 0.0
    assert T.tau[0][0] == 0.0
    assert not math.isnan(T.tau[1][2])
