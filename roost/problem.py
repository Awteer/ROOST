"""問題データと設定．

地点の通し番号（表の添字）
--------------------------
* 0              ：デポ（出発・帰着は同じ地点）
* 1..n           ：客（客の番号と同じ）
* n+1 .. n+|R|   ：NCR の候補地点（候補 ℓ = 0..|R|-1 は地点 n+1+ℓ）

ROOST にはコピーという概念がない．同じ NCR の地点に 2 回止まれば，別の停車（別の uid）が
同じ地点を指すだけ（docs/HANDOFF_20261026.md §4.2）．
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    """1 つの地点（座標 km，標高 m）．"""

    x_km: float
    y_km: float
    z_m: float


@dataclass(frozen=True)
class Problem:
    """問題データ．作った後は変更しない．"""

    name: str
    depot: Point
    customers: tuple[Point, ...]     # 客 1..n の地点（customers[j-1] が客 j）
    demands_kg: tuple[float, ...]    # 客 1..n の需要 q_j
    ncr_points: tuple[Point, ...] = ()  # NCR の候補地点（ℓ = 0..|R|-1）

    @property
    def n(self) -> int:
        return len(self.customers)

    @property
    def n_ncr(self) -> int:
        return len(self.ncr_points)

    @property
    def n_locations(self) -> int:
        """表の大きさ：デポ 1 ＋ 客 n ＋ NCR の候補 |R|．"""
        return 1 + self.n + self.n_ncr

    def ncr_loc(self, ell: int) -> int:
        """NCR の候補 ℓ の地点番号．"""
        return self.n + 1 + ell

    def point(self, loc: int) -> Point:
        """地点番号 → 地点．"""
        if loc == 0:
            return self.depot
        if 1 <= loc <= self.n:
            return self.customers[loc - 1]
        return self.ncr_points[loc - self.n - 1]

    def demand(self, j: int) -> float:
        """客 j の需要．"""
        return self.demands_kg[j - 1]


@dataclass(frozen=True)
class Options:
    """モデルの切り替え．既定は「NCR あり・往復あり・ドローンの機体をトラックに含める（A11）」．

    NCR_MILP の ModelOptions と同じ意味の項目は同じ名前にしてある．
    """

    allow_loops: bool = True           # 停車往復（A7）
    depot_loops: bool = True           # 出発デポでの出発前の往復（A7，#17）
    include_drone_mass: bool = True    # トラックの質量に機上のドローンの機体を含める（A11）
    require_ncr_use: bool = True       # (N18) 訪れた NCR は必ず使う（A2）
    forbid_drone_early: bool = True    # ドローンの先着（回収点でトラックより先に着く）を禁止（決定ログ #8）
    max_visits: int | None = None      # 1 つの NCR の地点に止まれる回数の上限 c（A4）．None で上限なし
    tmax_h: float | None = None        # 完了時刻の上限 T_max [h]．None で上限なし
    lam_kwh_per_h: float = 0.0         # T_max の罰金の単価 λ [kWh/h]（探索で使う目的 f の値だけに効く）
    tol: float = 1e-6                  # 判定の許容誤差（時刻 [h]，積載 [kg]，電池 [kWh]）


def from_xiao(xi, ncr_points: tuple[Point, ...] = ()) -> Problem:
    """XIAO のインスタンス（xiao.instance.Instance）の客とデポをそのまま使い，NCR の候補を足す．"""
    d0 = xi.nodes[0]
    cs = [xi.nodes[i] for i in xi.customers]
    return Problem(
        name=xi.name,
        depot=Point(d0.x_km, d0.y_km, d0.elevation_m),
        customers=tuple(Point(c.x_km, c.y_km, c.elevation_m) for c in cs),
        demands_kg=tuple(c.demand_kg for c in cs),
        ncr_points=tuple(ncr_points),
    )
