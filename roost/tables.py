"""前もって計算する表（docs/HANDOFF_20261026.md §4.4）．

* 距離・勾配：2 地点の 3 次元距離 [km] と勾配 [rad]（XIAO の precompute・NCR_MILP の tables と同じ定義）
* トラックの走行時間 τ_ab [h]
* トラックのエネルギー：弧ごとに積載 W [kg] の凸な区分線形
      ct_ab(W) = max( c0_ab,  k_ab + s_ab · W )
  W は「積荷＋機上のドローンの機体」．c0 はアイドル分（急な下りで出力 ≤ 0 の枝），
  k + s W は出力が正の枝．xi/energy.py の式 (1)–(4) を W について分解したもの
* ドローン：客 j（ドローンで運べる重さの客だけ）について，
      往路 out_e[a, j]（荷あり，地点 a → 客 j），復路 back_e[j, b]（空，客 j → 地点 b）
  とそれぞれの所要時間．出撃 (a, j, b) のエネルギーは out_e[a, j] + back_e[j, b]，往復は b = a
  （垂直の上昇・下降は往路・復路に 1 組ずつ入っている．式 (6) の和と同じ）

ここの値が xiao/energy.py の関数を直接呼んだ値と一致することは tests/test_tables.py で確かめる．
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from xiao import energy as E
from xiao.params import EnergyParams

from .problem import Problem


def geometry(p, q) -> tuple[float, float]:
    """2 地点の 3 次元距離 [km] と勾配 [rad]．"""
    h = math.hypot(p.x_km - q.x_km, p.y_km - q.y_km)
    dz = q.z_m - p.z_m
    d = math.sqrt(h**2 + (dz / 1000.0) ** 2)
    al = math.atan2(dz, max(h * 1000.0, 1e-12))
    return d, al


@dataclass
class Tables:
    prob: Problem
    ep: EnergyParams
    dist: list[list[float]] = field(default_factory=list)     # [a][b] 3 次元距離 [km]
    alpha: list[list[float]] = field(default_factory=list)    # [a][b] 勾配 [rad]
    tau: list[list[float]] = field(default_factory=list)      # [a][b] トラックの走行時間 [h]
    c0: list[list[float]] = field(default_factory=list)       # [a][b] トラック：アイドルの枝 [kWh]
    k: list[list[float]] = field(default_factory=list)        # [a][b] トラック：出力が正の枝の定数 [kWh]
    s: list[list[float]] = field(default_factory=list)        # [a][b] トラック：出力が正の枝の傾き [kWh/kg]
    drone_ok: list[bool] = field(default_factory=list)        # [j] 客 j をドローンで運べる重さか（j = 0 は未使用）
    out_e: dict = field(default_factory=dict)                 # (a, j) → 往路のエネルギー [kWh]
    out_t: dict = field(default_factory=dict)                 # (a, j) → 往路の時間 [h]
    back_e: dict = field(default_factory=dict)                # (j, b) → 復路のエネルギー [kWh]
    back_t: dict = field(default_factory=dict)                # (j, b) → 復路の時間 [h]
    m_d_kg: float = 0.0                                       # ドローンの機体 [kg]
    Q_t: float = 0.0                                          # トラックの積載上限 [kg]
    Q_d: float = 0.0                                          # ドローンの積載上限 [kg]
    cap_b: float = 0.0                                        # ドローンの電池 [kWh]

    def truck_energy(self, a: int, b: int, w_kg: float) -> float:
        """弧 a → b を積載 w_kg（積荷＋機上の機体）で走るエネルギー [kWh]．"""
        return max(self.c0[a][b], self.k[a][b] + self.s[a][b] * w_kg)

    def trip(self, a: int, j: int, b: int) -> tuple[float, float]:
        """出撃（b ≠ a）または往復（b = a）のエネルギー [kWh] と時間 [h]．客 j がドローンで運べることが前提．"""
        return self.out_e[a, j] + self.back_e[j, b], self.out_t[a, j] + self.back_t[j, b]


def build_tables(prob: Problem, ep: EnergyParams = EnergyParams()) -> Tables:
    tp, dp = ep.truck, ep.drone
    T = Tables(prob=prob, ep=ep)
    L = prob.n_locations
    pts = [prob.point(a) for a in range(L)]
    T.m_d_kg = dp.tare_weight_kg
    T.Q_t, T.Q_d, T.cap_b = tp.max_load_kg, dp.max_payload_kg, dp.battery_kwh

    # ---------------- 距離・勾配・トラック ----------------
    v_ms = tp.speed_kmph / 3.6
    zeta = E.transmission_efficiency(tp.speed_kmph)
    acc = tp.acceleration_frequency * 0.504 / (2.0 * 10.0**3 * 3.6) * tp.speed_kmph**3   # 加速の項の係数（質量に掛かる）
    air = (tp.air_density * tp.air_drag / (2.0 * 10.0**3)) * tp.frontal_area_m2 * v_ms**3  # 空気抵抗（質量によらない）
    T.dist = [[0.0] * L for _ in range(L)]
    T.alpha = [[0.0] * L for _ in range(L)]
    T.tau = [[0.0] * L for _ in range(L)]
    T.c0 = [[0.0] * L for _ in range(L)]
    T.k = [[0.0] * L for _ in range(L)]
    T.s = [[0.0] * L for _ in range(L)]
    for a in range(L):
        for b in range(L):
            d, al = geometry(pts[a], pts[b])
            T.dist[a][b], T.alpha[a][b] = d, al
            T.tau[a][b] = d / tp.speed_kmph
            if d <= 0.0:
                continue   # 同じ地点（デポ → デポなど）は 0 kWh，0 h
            # 式(1)：P^T = A·m + B（m [t]）．A は質量 1 t あたりの出力，B は空気抵抗
            a_coef = tp.g * v_ms * (math.sin(al) + tp.rolling_resistance * math.cos(al)) + acc
            base = (d / tp.speed_kmph) * tp.diesel_nhv_kwh_per_l               # 走行時間 × NHV
            c0 = base * tp.fuel_idle_lph                                        # アイドル分
            c1 = base * (tp.fuel_full_lph - tp.fuel_idle_lph) / (zeta * tp.engine_power_kw)
            T.c0[a][b] = c0
            T.k[a][b] = c0 + c1 * (a_coef * tp.tare_weight_ton + air)           # 積載 0 での出力が正の枝
            T.s[a][b] = c1 * a_coef / 1000.0                                    # 積載 1 kg あたり

    # ---------------- ドローンの往路・復路 ----------------
    eta3 = dp.engine_efficiency * dp.transmission_efficiency * dp.charging_efficiency
    vd, hh = dp.speed_kmph, dp.vertical_altitude_km
    m_empty = dp.tare_weight_kg
    vert_empty = E.drone_vertical_energy_kwh(m_empty, dp)
    T.drone_ok = [False] * (prob.n + 1)
    for j in range(1, prob.n + 1):
        q = prob.demand(j)
        if q > T.Q_d + 1e-9:
            continue
        T.drone_ok[j] = True
        vert_loaded = E.drone_vertical_energy_kwh(m_empty + q, dp)
        for a in range(L):
            if a == j:
                continue
            d_aj = T.dist[a][j]
            t = (2.0 * hh + d_aj) / vd
            T.out_t[a, j] = t
            T.out_e[a, j] = ((vert_loaded + E.drone_leg_energy_kwh(m_empty + q, d_aj, T.alpha[a][j], dp)) / eta3
                             + dp.internal_aux_kw * t / dp.charging_efficiency)
            d_ja = T.dist[j][a]
            t = (2.0 * hh + d_ja) / vd
            T.back_t[j, a] = t
            T.back_e[j, a] = ((vert_empty + E.drone_leg_energy_kwh(m_empty, d_ja, T.alpha[j][a], dp)) / eta3
                              + dp.internal_aux_kw * t / dp.charging_efficiency)
    return T
