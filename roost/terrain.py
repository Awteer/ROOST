"""坂道都市モデルの人工地形（案 C：海へ向かう全体の傾き＋尾根と谷＋細かい起伏）．

座標：km．x は海岸線に沿う向き，y は海岸から内陸へ向かう向き．領域は [-L/2, L/2] × [-L/2, L/2]．
海岸線は y = -L/2（下の辺）．標高は m．

    z(x, y) = z_reg(y) + w(y) · ( A_r · ridge(x, y) + n(x, y) )

* z_reg(y) = s · (y + L/2) · 1000            全体の傾き（勾配 s．海岸で 0 m）．理論の「ポテンシャル」の部分
* ridge(x, y) = sin(2π (x + δ(y)) / λ)        海へ向かって流れる尾根と谷（間隔 λ）．δ(y) で少し蛇行させる
* n(x, y)                                      フラクタルな細かい起伏（ハースト指数 H，RMS を指定）
* w(y) = min(1, (y + L/2) / W)                 海岸付近は平地（埋め立て地・港），内陸ほど起伏が大きい
* 最後に 0 m 未満は 0 m に切る（海面より下にしない）．傾き 0 のときは切らずに全体を持ち上げる

既定値（A_r=30 m，λ=1.6 km，細かい起伏 RMS 45 m，H=1.0）は，熱海の道路ノードの統計（下）に
seed 0〜3 の平均で 5% 程度まで合わせたもの（残り RMS 41.3 m，差の RMS 50 m:3.5，200 m:11.9，1 km:39.0 m）．

熱海の道路ノード（CITY results/atami_area/area_nodes.csv，2.8 km 四方，742 点）から測った値（2026-11-04）：
  全体の傾き 8.0%，傾きを引いた残りの RMS 42.5 m，
  残りの差の RMS（半バリオグラムの平方根）：50 m で 3.4 m，200 m で 11.4 m，1000 m で 42.6 m（ハースト指数 約 0.8）
道路ノードは道路の上の点なので，地形全体より穏やかな側に偏っている可能性がある．
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class TerrainSpec:
    side_km: float = 5.0          # 領域の 1 辺 L
    slope: float = 0.08           # 全体の傾き s（熱海 8%）
    ridge_amp_m: float = 30.0     # 尾根と谷の振幅 A_r（熱海の統計に合わせた値．2026-11-04）
    ridge_lambda_km: float = 1.6  # 尾根の間隔 λ
    meander_km: float = 0.25      # 尾根の蛇行の大きさ
    noise_rms_m: float = 45.0     # 細かい起伏の RMS
    hurst: float = 1.0            # 細かい起伏のハースト指数
    coast_flat_km: float = 0.4    # 海岸から起伏が満ちるまでの距離 W
    res_m: float = 20.0           # 格子の間隔
    seed: int = 0                 # 地形の乱数（客の配置とは別）


def _fractal_noise(n: int, res_m: float, hurst: float, rms: float, rng: np.random.Generator) -> np.ndarray:
    """スペクトル合成で n×n のフラクタルな面を作る．パワースペクトル ∝ k^-(2H+2)．平均 0，RMS = rms．"""
    if rms <= 0.0:
        return np.zeros((n, n))
    kx = np.fft.fftfreq(n, d=res_m)
    ky = np.fft.fftfreq(n, d=res_m)
    k = np.hypot(kx[None, :], ky[:, None])
    k[0, 0] = np.inf                       # 平均の成分は 0 にする
    amp = k ** (-(hurst + 1.0))            # 振幅 = パワーの平方根
    phase = np.exp(2j * np.pi * rng.random((n, n)))
    field = np.real(np.fft.ifft2(amp * phase))
    field -= field.mean()
    field *= rms / field.std()
    return field


@dataclass
class Terrain:
    spec: TerrainSpec
    xs: np.ndarray = field(repr=False)   # 格子の x [km]
    ys: np.ndarray = field(repr=False)   # 格子の y [km]
    z: np.ndarray = field(repr=False)    # z[iy, ix] [m]

    def height(self, x, y):
        """双一次補間で標高 [m]．x, y は km（スカラーでも配列でもよい）．領域の外は端の値．"""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        h = self.xs[1] - self.xs[0]
        fx = np.clip((x - self.xs[0]) / h, 0.0, len(self.xs) - 1.000001)
        fy = np.clip((y - self.ys[0]) / h, 0.0, len(self.ys) - 1.000001)
        i0 = np.floor(fx).astype(int)
        j0 = np.floor(fy).astype(int)
        tx = fx - i0
        ty = fy - j0
        z = self.z
        return ((1 - tx) * (1 - ty) * z[j0, i0] + tx * (1 - ty) * z[j0, i0 + 1]
                + (1 - tx) * ty * z[j0 + 1, i0] + tx * ty * z[j0 + 1, i0 + 1])


def make_terrain(spec: TerrainSpec) -> Terrain:
    L = spec.side_km
    n = int(round(L * 1000.0 / spec.res_m)) + 1
    xs = np.linspace(-L / 2, L / 2, n)
    ys = np.linspace(-L / 2, L / 2, n)
    X, Y = np.meshgrid(xs, ys)               # X[iy, ix]
    rng = np.random.default_rng(spec.seed)
    yy = Y + L / 2                           # 海岸からの距離 [km]
    z_reg = spec.slope * yy * 1000.0
    w = np.minimum(1.0, yy / spec.coast_flat_km) if spec.coast_flat_km > 0 else np.ones_like(yy)
    # 蛇行：y の滑らかな関数（低い周波数の乱数）
    meander = np.zeros_like(Y)
    if spec.meander_km > 0:
        for _ in range(3):
            f = rng.uniform(0.2, 0.8)        # 1 km あたりの周期の数
            ph = rng.uniform(0, 2 * np.pi)
            meander += np.sin(2 * np.pi * f * yy + ph)
        meander *= spec.meander_km / 3.0
    phase0 = rng.uniform(0, 2 * np.pi)
    ridge = np.sin(2 * np.pi * (X + meander) / spec.ridge_lambda_km + phase0) if spec.ridge_amp_m > 0 else 0.0
    noise = _fractal_noise(n, spec.res_m, spec.hurst, spec.noise_rms_m, rng)
    z = z_reg + w * (spec.ridge_amp_m * ridge + noise)
    if spec.slope > 0:
        z = np.maximum(z, 0.0)       # 海面より下にしない（海岸付近は w が小さいので切られるのは僅か）
    else:
        z = z - z.min()              # 傾きがないときは全体を持ち上げる（定数のずれはエネルギーに効かない）
    return Terrain(spec=spec, xs=xs, ys=ys, z=z)


def residual_stats(t: Terrain, n_points: int = 742, seed: int = 1) -> dict:
    """熱海の道路ノードと同じ統計：一様に点を取り，平面を引いた残りの RMS と半バリオグラムの平方根．"""
    rng = np.random.default_rng(seed)
    L = t.spec.side_km
    x = rng.uniform(-L / 2, L / 2, n_points)
    y = rng.uniform(-L / 2, L / 2, n_points)
    z = t.height(x, y)
    A = np.c_[x * 1000, y * 1000, np.ones_like(x)]
    c, *_ = np.linalg.lstsq(A, z, rcond=None)
    res = z - A @ c
    d = np.hypot(x[:, None] - x[None], y[:, None] - y[None]) * 1000
    g2 = (res[:, None] - res[None]) ** 2 / 2
    vg = {}
    for b in (50, 200, 1000):
        m = (d > b * 0.7) & (d <= b)
        vg[b] = float(np.sqrt(g2[m].mean())) if m.any() else float("nan")
    return dict(plane_grad=float(np.hypot(c[0], c[1])), residual_rms=float(res.std()),
                vg50=vg[50], vg200=vg[200], vg1000=vg[1000], z_max=float(t.z.max()))


def line_grades(t: Terrain, p, q, ds_m: float = 20.0):
    """2 点 p=(x,y), q=(x,y) [km] を結ぶ直線を ds_m ごとに切り，各小区間の水平長 [m] と標高差 [m] を返す．"""
    h = float(np.hypot(q[0] - p[0], q[1] - p[1])) * 1000.0
    k = max(1, int(np.ceil(h / ds_m)))
    s = np.linspace(0.0, 1.0, k + 1)
    xs = p[0] + (q[0] - p[0]) * s
    ys = p[1] + (q[1] - p[1]) * s
    z = t.height(xs, ys)
    return np.full(k, h / k), np.diff(z)
