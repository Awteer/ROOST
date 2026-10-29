"""ALNS の本体（Sacramento 2019 Algorithm 1 を土台にした，docs/DESIGN_20261029.md の決定どおりの版）．

* 止める条件：反復回数（Sacramento は CPU 時間．結果の再現性のため反復回数にする．決定 #3）
* 温度：T = T_start (1 − 反復/反復の上限)．T_start ＝ 係数 × 初期解の f（Xiao 2024 Table 3 と同じ係数）
* 受理：SA．良くなれば必ず受理，悪くなれば確率 exp((f(S) − f(S'))/T)
* 重み：壊す側も直す側も適応させる（決定 #4）．セグメント（既定 100 反復）ごとに
      w ← γ w + (1 − γ) π/θ   （π：セグメント内の点数の合計，θ：使った回数）
  点数は σ1（最良解を更新），σ2（受理・今の解より良い），σ3（受理・今の解より悪い），0（棄却）
* 改善なしが noImpvMax 回続いたら最良解に戻る
* T_max（決定 #2・#11）：f ＝ エネルギー＋λ·(T_max の超過)．λ の初期値は初期解の「エネルギー ÷ 完了時刻」．
  100 反復ごとに，作った解のうち T_max を守れた割合が 3 割未満なら λ を 1.2 倍，3 割を超えたら 0.85 倍．
  λ を変えたら今の解・最良解の f を計算し直す．返すのは T_max を守った解の中の最良だけ
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .evaluate import Evaluation
from .initial import add_drones, nearest_neighbor, string_relocation
from .moves import Ctx, SearchParams
from .operators import DESTROY, REPAIR, finish, removal_count
from .problem import Options, Problem
from .solution import Solution
from .tables import Tables


@dataclass
class ALNSConfig:
    iterations: int = 1000
    no_impv_max: int = 50
    gamma: float = 0.90
    sigma: tuple[float, float, float] = (33.0, 9.0, 13.0)
    seg_max: int = 100
    t0_factor_small: float = 0.5056       # 客 12 人以下（Xiao 2024 Table 3）
    t0_factor_large: float = 0.02         # それより多い（10/29：Sacramento の 0.004 では seed を変えても同じ解に落ちたので上げた）
    small_max_n: int = 12
    lam_window: int = 100                 # λ を見直す間隔
    lam_target: float = 0.3               # T_max を守れた割合の目標
    lam_up: float = 1.2
    lam_down: float = 0.85
    lam_range: float = 100.0              # λ を [λ0/100, 100 λ0] に止める
    initial_ncr: bool = True              # 初期解の第 3 段（ドローンの追加）で新しい NCR を開けるか
    destroy_ops: tuple[str, ...] = ("random", "cluster", "ncr_open", "ncr_close", "ncr_move")
    repair_ops: tuple[str, ...] = ("greedy_tfss", "nearby_tfss", "closest", "heavy")


@dataclass
class OpStats:
    used: int = 0
    accepted: int = 0
    new_best: int = 0
    weights: list[float] = field(default_factory=list)


@dataclass
class ALNSResult:
    best: Solution | None                 # T_max を守った解の中の最良（なければ None）
    best_eval: Evaluation | None
    initial_eval: Evaluation
    history: list[dict]                   # 反復ごとの記録
    destroy_stats: dict[str, OpStats]
    repair_stats: dict[str, OpStats]
    runtime_s: float
    n_evals: int
    seed: int


def _roulette(names, w, rng):
    tot = sum(w[n] for n in names)
    x = rng.random() * tot
    acc = 0.0
    for n in names:
        acc += w[n]
        if x <= acc:
            return n
    return names[-1]


def _safe_exp(x: float) -> float:
    if x >= 0:
        return math.inf
    if x < -700:
        return 0.0
    return math.exp(x)


def run_alns(prob: Problem, T: Tables, opts: Options, cfg: ALNSConfig = ALNSConfig(),
             sp: SearchParams = SearchParams(), seed: int = 1, initial: Solution | None = None,
             log_every: int = 0) -> ALNSResult:
    t0 = time.perf_counter()
    rng = random.Random(f"roost|seed={seed}")
    ctx = Ctx(prob=prob, T=T, opts=opts, sp=sp, rng=rng, lam=0.0)

    # ---- 初期解 ----
    # λ の初期値は「エネルギー ÷ 完了時刻」．Sacramento の第 3 段（ドローンの追加）から T_max の罰金を効かせるため，
    # 第 1・2 段（トラックだけの解）の値で決めてから第 3 段に進む
    use_tmax = opts.tmax_h is not None
    if initial is not None:
        S = initial.copy()
        ev_t = ctx.ev_final(finish(ctx, S))
        lam0 = (ev_t.energy_kwh / ev_t.completion_h) if (use_tmax and ev_t.completion_h > 0) else 0.0
        ctx.lam = lam0
    else:
        S = string_relocation(ctx, nearest_neighbor(ctx))
        ev_t = ctx.ev_final(S)
        lam0 = (ev_t.energy_kwh / ev_t.completion_h) if (use_tmax and ev_t.completion_h > 0) else 0.0
        ctx.lam = lam0
        S = add_drones(ctx, S, with_ncr=cfg.initial_ncr)
    S = finish(ctx, S)
    ev_S = ctx.ev_final(S)
    if not ev_S.feasible:
        raise RuntimeError(f"initial solution is not feasible: {ev_S.errors}")
    ev0 = ev_S

    def fval(ev: Evaluation) -> float:
        return ctx.f(ev)

    f_S = fval(ev_S)
    best_feas, best_feas_ev = (S.copy(), ev_S) if ev_S.within_tmax else (None, None)
    best_pen, best_pen_ev = S.copy(), ev_S          # 罰金込みの最良（実行可能な解がまだないときの戻り先）
    small = prob.n <= cfg.small_max_n
    t_start = (cfg.t0_factor_small if small else cfg.t0_factor_large) * f_S

    names_d = [n for n in cfg.destroy_ops]
    names_r = [n for n in cfg.repair_ops]
    w_d = {n: 1.0 for n in names_d}
    w_r = {n: 1.0 for n in names_r}
    sc_d = {n: 0.0 for n in names_d}
    sc_r = {n: 0.0 for n in names_r}
    use_d = {n: 0 for n in names_d}
    use_r = {n: 0 for n in names_r}
    st_d = {n: OpStats() for n in names_d}
    st_r = {n: OpStats() for n in names_r}
    history = []
    no_impv = 0
    seg = 0
    win_total = win_ok = 0

    for it in range(cfg.iterations):
        dn = _roulette(names_d, w_d, rng)
        rn = _roulette(names_r, w_r, rng)
        beta = removal_count(ctx)
        cand = S.copy()
        try:
            pool = DESTROY[dn](ctx, cand, beta)
            cand = REPAIR[rn](ctx, cand, pool)
            cand = finish(ctx, cand)
            ev_c = ctx.ev_final(cand)
        except RuntimeError:
            ev_c = None
        f_c = fval(ev_c) if ev_c is not None else math.inf
        if ev_c is not None and ev_c.feasible:
            win_total += 1
            win_ok += int(ev_c.within_tmax)

        T_now = t_start * (1.0 - it / cfg.iterations)
        f_old = f_S
        if f_c < f_S:
            accepted = True
        elif T_now > 0 and f_c < math.inf:
            accepted = rng.random() < _safe_exp((f_S - f_c) / T_now)
        else:
            accepted = False
        if accepted:
            S, ev_S, f_S = cand, ev_c, f_c

        new_best = False
        if accepted and ev_S.within_tmax and (best_feas_ev is None or ev_S.energy_kwh < best_feas_ev.energy_kwh - 1e-12):
            best_feas, best_feas_ev = S.copy(), ev_S
            new_best = True
        if accepted and f_S < fval(best_pen_ev) - 1e-12:
            best_pen, best_pen_ev = S.copy(), ev_S
            if best_feas_ev is None:
                new_best = True
        if new_best:
            no_impv = 0
        else:
            no_impv += 1
            if no_impv > cfg.no_impv_max:
                if best_feas is not None:
                    S, ev_S = best_feas.copy(), best_feas_ev
                else:
                    S, ev_S = best_pen.copy(), best_pen_ev
                f_S = fval(ev_S)
                no_impv = 0

        if new_best:
            score = cfg.sigma[0]
        elif accepted and f_c < f_old:
            score = cfg.sigma[1]
        elif accepted:
            score = cfg.sigma[2]
        else:
            score = 0.0
        sc_d[dn] += score
        sc_r[rn] += score
        use_d[dn] += 1
        use_r[rn] += 1
        for st, nm in ((st_d, dn), (st_r, rn)):
            st[nm].used += 1
            st[nm].accepted += int(accepted)
            st[nm].new_best += int(new_best)
        seg += 1
        if seg == cfg.seg_max:
            for w, sc, us, stt in ((w_d, sc_d, use_d, st_d), (w_r, sc_r, use_r, st_r)):
                for nm in w:
                    if us[nm] > 0:
                        w[nm] = cfg.gamma * w[nm] + (1.0 - cfg.gamma) * sc[nm] / us[nm]
                    w[nm] = max(w[nm], 1e-3)   # 0 になって二度と選ばれなくなるのを防ぐ
                    sc[nm] = 0.0
                    us[nm] = 0
                    stt[nm].weights.append(w[nm])
            seg = 0

        # ---- λ の見直し ----
        if use_tmax and (it + 1) % cfg.lam_window == 0 and win_total > 0:
            ratio = win_ok / win_total
            if ratio < cfg.lam_target:
                ctx.lam *= cfg.lam_up
            elif ratio > cfg.lam_target:
                ctx.lam *= cfg.lam_down
            ctx.lam = min(max(ctx.lam, lam0 / cfg.lam_range), lam0 * cfg.lam_range)
            f_S = fval(ev_S)   # λ が変わったので今の解の f を計算し直す（最良解は best_f() で毎回計算）
            win_total = win_ok = 0

        n_ncr = sum(1 for st in S.stops if st.kind == "ncr")
        history.append(dict(
            it=it + 1, destroy=dn, repair=rn, beta=beta, cand_kwh=(ev_c.energy_kwh if ev_c else math.inf),
            cand_completion_h=(ev_c.completion_h if ev_c else math.inf), accepted=accepted, new_best=new_best,
            cur_kwh=ev_S.energy_kwh, cur_completion_h=ev_S.completion_h, cur_ncr_stops=n_ncr,
            best_kwh=(best_feas_ev.energy_kwh if best_feas_ev else math.inf), lam=ctx.lam, temperature=T_now,
            elapsed_s=time.perf_counter() - t0,
        ))
        if log_every and (it + 1) % log_every == 0:
            print(f"  it {it + 1:6d}  cur {ev_S.energy_kwh:9.4f}  best {history[-1]['best_kwh']:9.4f}  "
                  f"ncr {n_ncr}  λ {ctx.lam:.3g}  {time.perf_counter() - t0:7.1f}s", flush=True)

    return ALNSResult(best=best_feas, best_eval=best_feas_ev, initial_eval=ev0, history=history,
                      destroy_stats=st_d, repair_stats=st_r, runtime_s=time.perf_counter() - t0,
                      n_evals=ctx.n_evals, seed=seed)
