"""NCR_MILP の結果（CSV）を ROOST の問題・設定・解に直す．評価器の照合に使う．

対象（NCR_MILP の results/）
---------------------------
* ncr_value_map/value_map.csv，ncr_value_map_n8/value_map.csv（value_map.py）
  条件：往復なし・デポでの往復なし・機体をトラックに含める・トラック 1 台・NCR は 1 地点（コピー 1 つ）
  列 x, y, z が空の行は NCR なし（基準）
* tmax_8.20.9.a/sweep.csv（tmax_sweep.py）
  条件は mode_id の (1)〜(5)（compare_modes.modes(depot_loops=True)）．NCR は r0 = (-10/3, 10/3)，標高は Xiao の地形

CSV の経路の書き方（NCR_MILP の instance.label）
----------------------------------------------
"0" 出発デポ，"0'" 帰着デポ，"c{j}" 客 j，"r{ℓ}" NCR の候補 ℓ（コピーが 2 つ以上なら "r{ℓ}^{s}"）．
トラックが出発しない解は route が ["0"] だけ．
"""

from __future__ import annotations

import json
from dataclasses import replace

from xiao import generate_instance
from xiao.instance import terrain_height_m

from .problem import Options, Point, Problem, from_xiao
from .solution import Loop, Solution, Sortie, Stop

# value_map.py の OPTS（往復なし，デポでの往復なし，機体を含める，トラック 1 台）とコピー 1 つ
VALUE_MAP_OPTIONS = Options(allow_loops=False, depot_loops=False, include_drone_mass=True, max_visits=1)

# tmax_sweep.py の 5 条件．(名前, NCR を使うか, Options)
TMAX_MODES = {
    1: ("(1) NCR なし・トラックのみ", False, Options(allow_loops=False, depot_loops=False, include_drone_mass=False,
                                                    max_visits=1)),
    2: ("(2) NCR なし・往復なし", False, VALUE_MAP_OPTIONS),
    3: ("(3) NCR なし・往復あり", False, Options(allow_loops=True, depot_loops=True, include_drone_mass=True,
                                               max_visits=1)),
    4: ("(4) NCR あり・往復なし", True, VALUE_MAP_OPTIONS),
    5: ("(5) NCR あり・往復あり", True, Options(allow_loops=True, depot_loops=True, include_drone_mass=True,
                                              max_visits=1)),
}


def xiao_instance(name: str):
    """"6.20.1.a" のような名前から XIAO のインスタンスを作る（value_map.py と同じ呼び方）．"""
    n, d, m, h = name.split(".")
    return generate_instance(int(n), float(d), int(m), h)


def solution_from_labels(route: list[str], sorties: list[list[str]], loops: list[list[str]]) -> Solution:
    """ラベルの列から ROOST の解を作る．uid は列の位置の番号（出発デポ 0，…，帰着デポ）．"""
    labels = list(route)
    if labels == ["0"]:
        labels = ["0", "0'"]          # トラックが出発しない解：出発デポ → 帰着デポ（距離 0）
    stops: list[Stop] = []
    uid_of: dict[str, int] = {}
    for p, lab in enumerate(labels):
        if lab in ("0", "0'"):
            st = Stop(uid=p, kind="depot", ref=0)
        elif lab.startswith("c"):
            st = Stop(uid=p, kind="customer", ref=int(lab[1:]))
        elif lab.startswith("r"):
            st = Stop(uid=p, kind="ncr", ref=int(lab[1:].split("^")[0]))
        else:
            raise ValueError(f"unknown label {lab}")
        if lab in uid_of:
            raise ValueError(f"label {lab} appears twice in the route")
        uid_of[lab] = p
        stops.append(st)
    drone: dict[int, Loop | Sortie] = {}
    for (i, j, k) in sorties:
        cj = int(j[1:])
        drone[cj] = Sortie(launch=uid_of[i], retrieve=uid_of[k])
    for (i, j) in loops:
        cj = int(j[1:])
        drone[cj] = Loop(at=uid_of[i])
    return Solution(stops=stops, drone=drone)


def value_map_case(row: dict) -> tuple[Problem, Options, Solution]:
    """value_map.csv の 1 行 → (問題, 設定, 解)．"""
    xi = xiao_instance(row["instance"])
    ncr = () if row["x"] in ("", None) else (Point(float(row["x"]), float(row["y"]), float(row["z"])),)
    prob = from_xiao(xi, ncr)
    sol = solution_from_labels(json.loads(row["route"]), json.loads(row["sorties"]), [])
    return prob, VALUE_MAP_OPTIONS, sol


def tmax_case(row: dict, instance: str = "8.20.9.a",
              ncr_xy: tuple[float, float] = (-10.0 / 3.0, 10.0 / 3.0)) -> tuple[Problem, Options, Solution]:
    """sweep.csv の 1 行（解がある行）→ (問題, 設定, 解)．"""
    xi = xiao_instance(instance)
    _title, use_ncr, opts = TMAX_MODES[int(row["mode_id"])]
    ncr = ()
    if use_ncr:
        centers = [(xi.nodes[i].x_km, xi.nodes[i].y_km) for i in xi.customers]
        x, y = ncr_xy
        ncr = (Point(x, y, terrain_height_m(x, y, centers, xi.xi)),)
    prob = from_xiao(xi, ncr)
    tm = row["tmax_min"]
    tmax_h = None if tm == "inf" else float(tm) / 60.0
    opts = replace(opts, tmax_h=tmax_h)
    sol = solution_from_labels(json.loads(row["route"]), json.loads(row["sorties"]), json.loads(row["loops"]))
    return prob, opts, sol
