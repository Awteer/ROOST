"""前もって計算する表（docs/HANDOFF_20261026.md §4.4）．

* 距離・勾配：2 地点の 3 次元距離 [km] と勾配 [rad]（XIAO の precompute・NCR_MILP の tables と同じ定義）
* トラックの走行時間 τ_ab [h]
* 地形あり（Problem.terrain が None でない．2026-11-04）：トラックの弧 a → b を，2 点を結ぶ直線に沿って
  terrain_ds_m ごとの小区間に切り，小区間ごとに式 (1)–(4) の max(アイドル，出力が正の枝) を足す．
  途中の上り下り（ブレーキで捨てる分）がエネルギーに入る．小区間を積載の範囲 [0, W_hi] で
      いつもアイドル（出力 ≤ 0）→ 定数 c0_i ／ いつも出力が正 → k_i + s_i W ／ 範囲の中で切り替わる → そのまま持つ
  の 3 つに分け，弧のエネルギーを  E(W) = C + S·W + Σ_band max(c0_i, k_i + s_i W)  と厳密に表す．
  走行時間は小区間の 3 次元の長さの和 ÷ 速さ．ドローンの距離・勾配（dist，alpha）は両端の直線のまま
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
    integrated: bool = False                                  # 地形の上で積分した表か
    tC: list[list[float]] = field(default_factory=list)       # [a][b] 積分：定数の部分 [kWh]
    tS: list[list[float]] = field(default_factory=list)       # [a][b] 積分：積載 1 kg あたり [kWh/kg]
    tband: dict = field(default_factory=dict)                 # (a, b) → ((c0, k, s), ...) 範囲の中で切り替わる小区間

    def truck_energy(self, a: int, b: int, w_kg: float) -> float:
        """弧 a → b を積載 w_kg（積荷＋機上の機体）で走るエネルギー [kWh]．"""
        if self.integrated:
            e = self.tC[a][b] + self.tS[a][b] * w_kg
            band = self.tband.get((a, b))
            if band:
                for c0, k, s in band:
                    e += max(c0, k + s * w_kg)
            return e
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

    if prob.terrain is not None:
        _integrate_truck(T, prob, pts, ep, v_ms, zeta, acc, air)

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


def _integrate_truck(T: Tables, prob: Problem, pts, ep: EnergyParams, v_ms: float, zeta: float,
                     acc: float, air: float) -> None:
    """地形の上でトラックの弧を積分する（モジュールの説明を参照）．T.tau，T.tC，T.tS，T.tband を書き，
    T.c0・T.k・T.s は使わない印として NaN にする（truck_energy は integrated のときそれらを読まない）．"""
    import numpy as np

    tp = ep.truck
    ter = prob.terrain
    ds = float(prob.terrain_ds_m)
    L = prob.n_locations
    w_hi = sum(prob.demands_kg) + T.m_d_kg + 1.0     # 積載の範囲の上限（全部の荷物＋機上の機体）
    nan = float("nan")
    T.integrated = True
    T.tC = [[0.0] * L for _ in range(L)]
    T.tS = [[0.0] * L for _ in range(L)]
    T.tband = {}
    k_time = tp.diesel_nhv_kwh_per_l / tp.speed_kmph                       # 長さ 1 km あたりの「走行時間 × NHV」
    c1_per = (tp.fuel_full_lph - tp.fuel_idle_lph) / (zeta * tp.engine_power_kw)
    for a in range(L):
        pa = pts[a]
        for b in range(L):
            T.c0[a][b] = T.k[a][b] = T.s[a][b] = nan
            if a == b:
                T.tau[a][b] = 0.0
                continue
            pb = pts[b]
            h_km = math.hypot(pb.x_km - pa.x_km, pb.y_km - pa.y_km)
            if h_km <= 0.0:
                T.tau[a][b] = 0.0
                continue
            m = max(1, int(math.ceil(h_km * 1000.0 / ds)))
            u = np.linspace(0.0, 1.0, m + 1)
            z = np.asarray(ter.height(pa.x_km + (pb.x_km - pa.x_km) * u, pa.y_km + (pb.y_km - pa.y_km) * u),
                           dtype=float)
            # 両端は地点の標高に合わせる（地点の z_m は地形から取っているはずだが，念のため端を固定する）
            z[0], z[-1] = pa.z_m, pb.z_m
            dz = np.diff(z)                                   # [m]
            hseg = h_km / m                                   # [km]
            d = np.sqrt(hseg ** 2 + (dz / 1000.0) ** 2)       # 小区間の 3 次元の長さ [km]
            al = np.arctan2(dz, hseg * 1000.0)
            base = d * k_time
            c0 = base * tp.fuel_idle_lph
            c1 = base * c1_per
            a_coef = tp.g * v_ms * (np.sin(al) + tp.rolling_resistance * np.cos(al)) + acc
            k = c0 + c1 * (a_coef * tp.tare_weight_ton + air)
            s = c1 * a_coef / 1000.0
            f_lo = k - c0                                     # 積載 0 での（出力が正の枝 − アイドル）
            f_hi = k + s * w_hi - c0
            idle = (f_lo <= 0.0) & (f_hi <= 0.0)
            lin = (f_lo >= 0.0) & (f_hi >= 0.0) & ~idle
            band = ~(idle | lin)
            T.tC[a][b] = float(c0[idle].sum() + k[lin].sum())
            T.tS[a][b] = float(s[lin].sum())
            if band.any():
                T.tband[a, b] = tuple(zip(c0[band].tolist(), k[band].tolist(), s[band].tolist()))
            T.tau[a][b] = float(d.sum()) / tp.speed_kmph
