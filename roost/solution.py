"""解の表し方 A：トラックの停車の列＋ドローン客ごとの配り方（docs/HANDOFF_20261026.md §4.1）．

* トラックの客は stops に，ドローンの客は drone の鍵に，ちょうど一方に 1 回だけ出る
* 出撃・往復は列の位置ではなく停車の uid で指す．停車を挿入しても指す先がずれず，
  同じ NCR の地点への再訪問も別の uid として区別できる
* stops の先頭は出発デポ，末尾は帰着デポ（同じ地点．uid は別）
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Stop:
    uid: int        # 停車ごとに固有
    kind: str       # "depot" | "customer" | "ncr"
    ref: int        # "customer"：客の番号（1..n），"ncr"：NCR の候補の番号 ℓ（0 始まり），"depot"：0


@dataclass(frozen=True)
class Loop:
    at: int         # 往復する停車の uid（発射と回収が同じ停車）


@dataclass(frozen=True)
class Sortie:
    launch: int     # 発射する停車の uid
    retrieve: int   # 回収する停車の uid


@dataclass
class Solution:
    stops: list[Stop]                                                   # トラックの停車の列
    drone: dict[int, Loop | Sortie] = field(default_factory=dict)       # ドローン客 j → 配り方

    def pos(self) -> dict[int, int]:
        """uid → 列の中の位置．列を変えたら毎回引き直す．"""
        return {st.uid: p for p, st in enumerate(self.stops)}

    def next_uid(self) -> int:
        """まだ使っていない uid．"""
        return 1 + max((st.uid for st in self.stops), default=-1)

    def copy(self) -> "Solution":
        return Solution(stops=list(self.stops), drone=dict(self.drone))


def loc_of(stop: Stop, n_customers: int) -> int:
    """停車 → 地点の通し番号（problem.py の約束：デポ 0，客 1..n，NCR の候補 ℓ は n+1+ℓ）．"""
    if stop.kind == "depot":
        return 0
    if stop.kind == "customer":
        return stop.ref
    if stop.kind == "ncr":
        return n_customers + 1 + stop.ref
    raise ValueError(f"unknown stop kind: {stop.kind}")
