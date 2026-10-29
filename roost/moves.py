"""解を書き換える基本の操作と，客 1 人の入れ方の候補（オペレータの部品）．

docs/DESIGN_20261029.md の決定に従う．
* 客の抜き方：ドローン客ならその配り方を消す．トラックの客なら停車を消し，その停車で発射・回収・往復していた
  ドローン客も抜く（Sacramento 2019 §4.2.1）
* 同じ NCR の地点の停車が隣り合ったら 1 つにまとめる（(N7)）．まとめるときは，後ろの停車を使っていた
  配り方を前の停車に付け替える（同じ地点なので，往路・復路のエネルギーは変わらない）
* 誰も使わない NCR の停車を消すのは，直した後だけ（壊した直後に消すと NCR が減る方向に偏るため．決定 #9）
* 入れ方の候補（客 j 1 人あたり）
    T   ：トラックの停車として位置 p に挿入
    O   ：既存の停車から往復
    S   ：既存の停車 p で発射，q で回収（q − p ≤ w）
    NO  ：NCR の候補 ℓ に新しく停まり，そこから往復
    NSL ：NCR の候補 ℓ に新しく停まり，そこで発射．回収は既存の停車（新しい停車から w 個以内の後ろ）
    NSR ：既存の停車（新しい停車から w 個以内の前）で発射，NCR の候補 ℓ の新しい停車で回収
  NCR の候補は，客 j への往復のエネルギーが小さい順に K 個．新しい停車を置く位置は，
  トラックの挿入の増分が一番小さい位置に決め打ちする（決定 #8）
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace

from .evaluate import Evaluation, evaluate
from .problem import Options, Problem
from .solution import Loop, Solution, Sortie, Stop, loc_of
from .tables import Tables


@dataclass
class SearchParams:
    """探索の定数．"""

    sortie_span: int = 3            # w：出撃の発射と回収の停車の間隔の上限
    ncr_k: int = 3                  # K：直す側で試す NCR の候補の数（客への往復のエネルギーが小さい順）
    ncr_open_radius_km: float | None = None   # D：NCR 開設で選ぶ候補の，今のトラック経路からの距離の上限（None で自動）
    ncr_move_k: int = 3             # NCR 移動：今の地点からトラックで近い候補のうち何個から選ぶか
    kappa: float = 0.15             # 破壊度（壊す客の数 β = min(max(c_low, κ n), c_lim)）
    c_low_range: tuple[int, int] = (1, 3)
    c_lim: int = 40
    nearby_radius_km: float | None = None     # Nearby-Area の「近い」の半径（None で自動）
    nearby_slack: float = 0.10      # Nearby-Area の第 2 段：直す前より 10% 以上悪くならない手から選ぶ
    max_fallback: int = 50          # トラックに入れられないときの逃げ道の上限
    phase2_scope: str = "all"       # TF-SS の第 2 段で替える候補："all"＝解の全員（Sacramento どおり），"inserted"＝直した客だけ（Xiao）


@dataclass
class Ctx:
    """探索の文脈：問題・表・設定と，前もって並べておく候補の順番．"""

    prob: Problem
    T: Tables
    opts: Options                   # 最終的な評価に使う設定
    sp: SearchParams
    rng: random.Random
    lam: float = 0.0                # T_max の罰金の単価 λ [kWh/h]（探索中に変わる）
    search_opts: Options = None     # 部分解の評価用（(N18) を課さない）
    loop_order: dict = field(default_factory=dict)   # 客 j → 往復のエネルギーが小さい順の NCR の候補 ℓ
    near_ncr: dict = field(default_factory=dict)     # 候補 ℓ → トラックの距離が近い順の他の候補
    n_evals: int = 0

    def __post_init__(self):
        self.search_opts = replace(self.opts, require_ncr_use=False)
        prob, T = self.prob, self.T
        for j in range(1, prob.n + 1):
            if not T.drone_ok[j]:
                continue
            cand = []
            for ell in range(prob.n_ncr):
                r = prob.ncr_loc(ell)
                e, _ = T.trip(r, j, r)
                if e <= T.cap_b + self.opts.tol:
                    cand.append((e, ell))
            cand.sort()
            self.loop_order[j] = [ell for _, ell in cand]
        for ell in range(prob.n_ncr):
            r = prob.ncr_loc(ell)
            others = sorted((T.dist[r][prob.ncr_loc(m)], m) for m in range(prob.n_ncr) if m != ell)
            self.near_ncr[ell] = [m for _, m in others]
        if self.sp.ncr_open_radius_km is None or self.sp.nearby_radius_km is None:
            pts = [prob.point(a) for a in range(prob.n + 1)]
            span = max(math.hypot(p.x_km - q.x_km, p.y_km - q.y_km) for p in pts for q in pts) or 1.0
            if self.sp.ncr_open_radius_km is None:
                self.sp = replace(self.sp, ncr_open_radius_km=0.25 * span)
            if self.sp.nearby_radius_km is None:
                self.sp = replace(self.sp, nearby_radius_km=0.25 * span)

    # ---------------- 評価 ----------------
    def ev(self, sol: Solution) -> Evaluation:
        """部分解の評価（まだ配っていない客・使われていない NCR をエラーにしない）．"""
        self.n_evals += 1
        return evaluate(self.prob, self.T, sol, self.search_opts, allow_unserved=True)

    def ev_final(self, sol: Solution) -> Evaluation:
        """完成した解の評価（設定どおり．全員を配っていること，(N18) を含む）．"""
        self.n_evals += 1
        return evaluate(self.prob, self.T, sol, self.opts)

    def f(self, ev: Evaluation) -> float:
        """探索で使う目的 f＝エネルギー＋λ·(T_max の超過)．形のエラーがあれば無限大．"""
        if not ev.feasible:
            return math.inf
        return ev.energy_kwh + self.lam * ev.tmax_excess_h

    def loc(self, st: Stop) -> int:
        return loc_of(st, self.prob.n)


# ---------------------------------------------------------------------------
# 抜く・まとめる・消す
# ---------------------------------------------------------------------------


def users_of(sol: Solution, uid: int) -> list[int]:
    """停車 uid で発射・回収・往復するドローン客．"""
    out = []
    for j, how in sol.drone.items():
        if isinstance(how, Loop):
            if how.at == uid:
                out.append(j)
        elif how.launch == uid or how.retrieve == uid:
            out.append(j)
    return out


def remove_stop(sol: Solution, uid: int, pool: list[int]) -> None:
    """停車を消し，その停車を使っていたドローン客を抜く（トラックの客の停車なら，その客も抜く）．"""
    idx = next(p for p, st in enumerate(sol.stops) if st.uid == uid)
    st = sol.stops.pop(idx)
    for j in users_of(sol, uid):
        del sol.drone[j]
        pool.append(j)
    if st.kind == "customer":
        pool.append(st.ref)


def remove_customer(sol: Solution, j: int, pool: list[int]) -> None:
    """客 j を抜く．トラックの客なら，その停車にぶら下がるドローン客も抜く．"""
    if j in sol.drone:
        del sol.drone[j]
        pool.append(j)
        return
    for st in sol.stops:
        if st.kind == "customer" and st.ref == j:
            remove_stop(sol, st.uid, pool)
            return
    raise KeyError(f"customer {j} is not in the solution")


def merge_same_ncr(sol: Solution) -> None:
    """同じ NCR の地点の停車が隣り合っていたら 1 つにまとめる（(N7)）．後ろの停車の配り方を前の停車へ付け替える．"""
    p = 0
    while p + 1 < len(sol.stops):
        a, b = sol.stops[p], sol.stops[p + 1]
        if a.kind == "ncr" and b.kind == "ncr" and a.ref == b.ref:
            for j, how in list(sol.drone.items()):
                if isinstance(how, Loop):
                    if how.at == b.uid:
                        sol.drone[j] = Loop(a.uid)
                else:
                    la = a.uid if how.launch == b.uid else how.launch
                    rb = a.uid if how.retrieve == b.uid else how.retrieve
                    sol.drone[j] = Loop(a.uid) if la == rb else Sortie(la, rb)
            sol.stops.pop(p + 1)
        else:
            p += 1


def drop_unused_ncr(sol: Solution) -> None:
    """誰も使わない NCR の停車を消す（直した後に呼ぶ）．消した結果隣り合った同じ地点はまとめる．"""
    used = set()
    for how in sol.drone.values():
        if isinstance(how, Loop):
            used.add(how.at)
        else:
            used.add(how.launch)
            used.add(how.retrieve)
    sol.stops = [st for st in sol.stops if st.kind != "ncr" or st.uid in used]
    merge_same_ncr(sol)


def ncr_visits(sol: Solution, ell: int) -> int:
    return sum(1 for st in sol.stops if st.kind == "ncr" and st.ref == ell)


def is_anchor(sol: Solution, uid: int) -> bool:
    """その停車で発射・回収・往復があるか．"""
    return bool(users_of(sol, uid))


# ---------------------------------------------------------------------------
# NCR の新しい停車を置く位置（トラックの挿入の増分が最小．決定 #8）
# ---------------------------------------------------------------------------


def cheapest_ncr_position(ctx: Ctx, sol: Solution, ev: Evaluation, ell: int) -> int | None:
    """NCR の候補 ℓ を挿入する位置 p（stops[p-1] と stops[p] の間）．置けなければ None．

    増分は弧の表の足し引き：E(a, r, W) + E(r, b, W) − E(a, b, W)．W は stops[p-1] を出るときの積荷＋機体
    （ドローンが機上かどうかは見ない近似．位置を決めるだけに使い，値は評価器で出し直す）．
    """
    opts = ctx.opts
    if opts.max_visits is not None and ncr_visits(sol, ell) >= opts.max_visits:
        return None
    T = ctx.T
    r = ctx.prob.ncr_loc(ell)
    m_d = T.m_d_kg if opts.include_drone_mass else 0.0
    best, best_p = math.inf, None
    for p in range(1, len(sol.stops)):
        sa, sb = sol.stops[p - 1], sol.stops[p]
        if (sa.kind == "ncr" and sa.ref == ell) or (sb.kind == "ncr" and sb.ref == ell):
            continue   # (N7)
        a, b = ctx.loc(sa), ctx.loc(sb)
        w = (ev.load_out_kg[p - 1] if p - 1 < len(ev.load_out_kg) else 0.0) + m_d
        d = T.truck_energy(a, r, w) + T.truck_energy(r, b, w) - T.truck_energy(a, b, w)
        if d < best:
            best, best_p = d, p
    return best_p


def insert_stop(sol: Solution, p: int, stop: Stop) -> None:
    sol.stops.insert(p, stop)


# ---------------------------------------------------------------------------
# 客 1 人の入れ方の候補
# ---------------------------------------------------------------------------


@dataclass
class Move:
    kind: str                   # "T" | "O" | "S" | "NO" | "NSL" | "NSR"
    j: int
    p: int = -1                 # 挿入位置（T，NO，NSL，NSR）
    a: int = -1                 # 既存の停車の uid（O：往復，S：発射，NSL：回収，NSR：発射）
    b: int = -1                 # S：回収の uid
    ell: int = -1               # NCR の候補（NO，NSL，NSR）

    def apply(self, sol: Solution) -> Solution:
        s = sol.copy()
        if self.kind == "T":
            insert_stop(s, self.p, Stop(uid=s.next_uid(), kind="customer", ref=self.j))
        elif self.kind == "O":
            s.drone[self.j] = Loop(self.a)
        elif self.kind == "S":
            s.drone[self.j] = Sortie(self.a, self.b)
        else:
            u = s.next_uid()
            insert_stop(s, self.p, Stop(uid=u, kind="ncr", ref=self.ell))
            if self.kind == "NO":
                s.drone[self.j] = Loop(u)
            elif self.kind == "NSL":
                s.drone[self.j] = Sortie(u, self.a)
            else:
                s.drone[self.j] = Sortie(self.a, u)
        return s


def truck_moves(sol: Solution, j: int, positions=None) -> list[Move]:
    ps = range(1, len(sol.stops)) if positions is None else positions
    return [Move("T", j, p=p) for p in ps]


def drone_moves(ctx: Ctx, sol: Solution, ev: Evaluation, j: int, with_ncr: bool = True) -> list[Move]:
    """客 j をドローンで配る候補（既存の停車からの往復・出撃，新しい NCR の停車からの往復・出撃）．"""
    prob, T, opts, sp = ctx.prob, ctx.T, ctx.opts, ctx.sp
    if not T.drone_ok[j] or not opts.drones_enabled:
        return []
    stops = sol.stops
    L = len(stops)
    locs = [ctx.loc(st) for st in stops]
    cap = T.cap_b + opts.tol
    out: list[Move] = []
    # 既存の停車からの往復
    if opts.allow_loops:
        for p in range(L - 1):                   # 帰着デポでは往復しない（#17）
            if p == 0 and not opts.depot_loops:
                continue
            if T.trip(locs[p], j, locs[p])[0] <= cap:
                out.append(Move("O", j, a=stops[p].uid))
    # 既存の停車の間の出撃
    for p in range(L - 1):
        for q in range(p + 1, min(p + sp.sortie_span, L - 1) + 1):
            if p == 0 and q == L - 1:
                continue                         # デポ発・デポ着（A9）
            if locs[p] == locs[q]:
                continue                         # 同じ地点どうしは往復と同じ
            if T.trip(locs[p], j, locs[q])[0] <= cap:
                out.append(Move("S", j, a=stops[p].uid, b=stops[q].uid))
    # 新しい NCR の停車
    if with_ncr and prob.n_ncr > 0:
        for ell in ctx.loop_order.get(j, [])[: sp.ncr_k]:
            pr = cheapest_ncr_position(ctx, sol, ev, ell)
            if pr is None:
                continue
            r = prob.ncr_loc(ell)
            if opts.allow_loops:
                out.append(Move("NO", j, p=pr, ell=ell))
            # 新しい停車は位置 pr に入り，既存の stops[pr:] は 1 つ後ろへずれる
            for q in range(pr, min(pr + sp.sortie_span, L)):       # 既存の stops[q]（新しい位置は q+1）で回収
                if locs[q] == r:
                    continue
                if T.trip(r, j, locs[q])[0] <= cap:
                    out.append(Move("NSL", j, p=pr, a=stops[q].uid, ell=ell))
            for q in range(max(0, pr - sp.sortie_span), pr):        # 既存の stops[q] で発射
                if locs[q] == r:
                    continue
                if T.trip(locs[q], j, r)[0] <= cap:
                    out.append(Move("NSR", j, p=pr, a=stops[q].uid, ell=ell))
    return out


def best_move(ctx: Ctx, sol: Solution, moves: list[Move]) -> tuple[Move | None, float, Solution | None]:
    """候補を全部評価して一番 f が小さいもの（実行可能なものだけ）．"""
    best, best_f, best_s = None, math.inf, None
    for mv in moves:
        s = mv.apply(sol)
        fv = ctx.f(ctx.ev(s))
        if fv < best_f:
            best, best_f, best_s = mv, fv, s
    return best, best_f, best_s


def scored_moves(ctx: Ctx, sol: Solution, moves: list[Move]) -> list[tuple[float, Move, Solution]]:
    """候補を全部評価して (f, 手, 解) の一覧（実行可能なものだけ）．"""
    out = []
    for mv in moves:
        s = mv.apply(sol)
        fv = ctx.f(ctx.ev(s))
        if fv < math.inf:
            out.append((fv, mv, s))
    return out


def insert_truck_fallback(ctx: Ctx, sol: Solution, j: int, pool: list[int]) -> Solution:
    """どこにもトラックで入れられないときの逃げ道：帰着デポの直前に入れ，そこを跨ぐ出撃の客を抜く．"""
    s = sol.copy()
    end_uid = s.stops[-1].uid
    for jj, how in list(s.drone.items()):
        if isinstance(how, Sortie) and how.retrieve == end_uid:
            del s.drone[jj]
            pool.append(jj)
    insert_stop(s, len(s.stops) - 1, Stop(uid=s.next_uid(), kind="customer", ref=j))
    return s
