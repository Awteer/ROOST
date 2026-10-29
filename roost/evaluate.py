"""形のチェックと評価器 v1（docs/HANDOFF_20261026.md §4.3，§4.4）．

評価器 v1 は，解を受け取るたびに列を前から 1 回なめて全部を計算し直す（差分の評価はしない）．
探索のオペレータは実行可能性の判定を持たず，この評価器だけを真実とする．

時刻の約束（決定ログ #14・#15，A8）
-----------------------------------
1 つの停車での出来事の順番は「到着 → 回収 → 往復 → 出発（＝発射）」．
* 回収：ドローンの帰着時刻が到着より前ならエラー（ドローンの先着の禁止．Options.forbid_drone_early）．
  準備完了の時刻は max(到着, 帰着)
* 往復：ドローンが機上にいることが必要．往復の時間を順に足す（往復どうしの順番は値を変えない）
* 発射：ドローンが機上にいることが必要．発射時刻＝出発時刻＝準備完了．回収点での帰着時刻を予約する
* 待ち＝出発時刻 − 到着時刻．トラックの待ちのエネルギーは 0（A6）
出発デポでは「往復 → 発射（＝出発）」．帰着デポでは回収だけ（往復は禁止．#17）．

トラックのエネルギー（A11）
---------------------------
弧のエネルギーは，その弧を走るときの「積荷＋（ドローンが機上なら）機体」の質量で計算する．
積荷の初期値＝トラックの客の荷物＋出発デポ以外から出すドローン客の荷物（出発デポで発射・往復する荷物は積まない）．
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .problem import Options, Problem
from .solution import Loop, Solution, Sortie, loc_of
from .tables import Tables


@dataclass
class Evaluation:
    feasible: bool                      # 形・同期・電池・容量のエラーがない（T_max は含めない）
    errors: list[str]
    truck_kwh: float
    drone_kwh: float
    completion_h: float                 # 帰着デポでの出発時刻（回収を含む）．トラックが動かなければ出発デポでの往復の終わり
    wait_h: float                       # トラックの待ちの合計（出発デポ以外の停車．NCR_MILP の check.py と同じ数え方）
    depot_loop_h: float                 # 出発デポでの往復の時間（出発が遅れる分．wait_h には入れない）
    tmax_excess_h: float                # max(0, 完了 − T_max)．T_max がなければ 0
    objective: float                    # f = トラック＋ドローン＋λ·(T_max の超過)
    arrival_h: list[float] = field(default_factory=list)     # 停車ごとの到着時刻（出発デポは 0）
    departure_h: list[float] = field(default_factory=list)   # 停車ごとの出発時刻
    load_out_kg: list[float] = field(default_factory=list)   # 停車を出るときの積荷 [kg]（機体を含めない）

    @property
    def energy_kwh(self) -> float:
        return self.truck_kwh + self.drone_kwh

    @property
    def within_tmax(self) -> bool:
        return self.tmax_excess_h <= 0.0


def _shape_errors(prob: Problem, T: Tables, sol: Solution, opts: Options) -> tuple[list[str], bool]:
    """§4.3 の形のチェック．2 つ目の戻り値は「時刻を追う計算に進めるか」（参照が壊れていたら False）．"""
    err: list[str] = []
    stops = sol.stops
    n = prob.n
    if len(stops) < 2:
        return ["stops must contain the start and end depots"], False
    if stops[0].kind != "depot" or stops[-1].kind != "depot":
        err.append("stops must start and end with a depot")
    for st in stops[1:-1]:
        if st.kind == "depot":
            err.append(f"depot in the middle of the route (uid {st.uid})")
    uids = [st.uid for st in stops]
    if len(set(uids)) != len(uids):
        return err + ["duplicate stop uid"], False
    for st in stops:
        if st.kind == "customer" and not (1 <= st.ref <= n):
            return err + [f"customer stop with bad ref {st.ref}"], False
        if st.kind == "ncr" and not (0 <= st.ref < prob.n_ncr):
            return err + [f"NCR stop with bad ref {st.ref}"], False
        if st.kind not in ("depot", "customer", "ncr"):
            return err + [f"unknown stop kind {st.kind}"], False
    pos = sol.pos()
    start_uid, end_uid = stops[0].uid, stops[-1].uid

    # ---- 客はちょうど 1 回（トラックかドローンのどちらか一方） ----
    served = {}
    for st in stops:
        if st.kind == "customer":
            served[st.ref] = served.get(st.ref, 0) + 1
    for j in sol.drone:
        if not (1 <= j <= n):
            return err + [f"drone customer {j} out of range"], False
        served[j] = served.get(j, 0) + 1
        if not T.drone_ok[j]:
            err.append(f"customer {j} too heavy for the drone ({prob.demand(j):.2f} kg)")
    for j in range(1, n + 1):
        if served.get(j, 0) != 1:
            err.append(f"customer {j} served {served.get(j, 0)} times")
    if err and any("too heavy" in e for e in err):
        return err, False   # 重い客をドローンにした解は往路の表がないので時刻を追えない

    # ---- 出撃・往復の参照と向き ----
    intervals = []   # (発射の位置, 回収の位置, 客)
    loop_pos = []    # (位置, 客)
    for j, how in sol.drone.items():
        if isinstance(how, Loop):
            if how.at not in pos:
                return err + [f"loop of customer {j} at unknown stop {how.at}"], False
            if not opts.allow_loops:
                err.append(f"loop of customer {j} but loops are disabled")
            if how.at == end_uid:
                err.append(f"loop of customer {j} at the end depot (#17)")
            if how.at == start_uid and not opts.depot_loops:
                err.append(f"loop of customer {j} at the start depot but depot loops are disabled")
            loop_pos.append((pos[how.at], j))
        elif isinstance(how, Sortie):
            if how.launch not in pos or how.retrieve not in pos:
                return err + [f"sortie of customer {j} refers to an unknown stop"], False
            p, q = pos[how.launch], pos[how.retrieve]
            if p >= q:
                err.append(f"sortie of customer {j}: retrieval is not after launch")
            if how.launch == start_uid and how.retrieve == end_uid:
                err.append(f"sortie of customer {j} from depot to depot (A9)")
            intervals.append((p, q, j))
        else:
            return err + [f"customer {j}: unknown service {how!r}"], False

    # ---- 出撃どうしが重ならない（(N24)–(N29)．回収した停車でそのまま次を発射するのは可） ----
    intervals.sort()
    for (p1, q1, j1), (p2, q2, j2) in zip(intervals, intervals[1:]):
        if p2 < q1:
            err.append(f"sorties of customers {j1} and {j2} overlap")
    # ---- 飛行中の停車では往復しない（(N30)） ----
    for (x, j) in loop_pos:
        for (p, q, js) in intervals:
            if p < x < q:
                err.append(f"loop of customer {j} at a stop inside the sortie of customer {js} (N30)")

    # ---- NCR：同じ地点の連続（(N7)），回数の上限（A4），使われない停車（(N18)） ----
    for a, b in zip(stops, stops[1:]):
        if a.kind == "ncr" and b.kind == "ncr" and a.ref == b.ref:
            err.append(f"consecutive stops at the same NCR location r{a.ref} (N7)")
    if opts.max_visits is not None:
        count = {}
        for st in stops:
            if st.kind == "ncr":
                count[st.ref] = count.get(st.ref, 0) + 1
        for ell, c in count.items():
            if c > opts.max_visits:
                err.append(f"NCR location r{ell} visited {c} times > max_visits {opts.max_visits} (A4)")
    if opts.require_ncr_use:
        used = set()
        for how in sol.drone.values():
            if isinstance(how, Loop):
                used.add(how.at)
            else:
                used.add(how.launch)
                used.add(how.retrieve)
        for st in stops:
            if st.kind == "ncr" and st.uid not in used:
                err.append(f"NCR stop r{st.ref} (uid {st.uid}) is visited but unused (N18)")
    return err, True


def evaluate(prob: Problem, T: Tables, sol: Solution, opts: Options = Options()) -> Evaluation:
    """解を評価する．エラーがあっても計算できる所までは計算して返す（feasible=False）．"""
    errors, can_run = _shape_errors(prob, T, sol, opts)
    inf = float("inf")
    if not can_run:
        return Evaluation(feasible=False, errors=errors, truck_kwh=inf, drone_kwh=inf, completion_h=inf,
                          wait_h=inf, depot_loop_h=inf, tmax_excess_h=inf, objective=inf)
    tol = opts.tol
    n = prob.n
    stops = sol.stops
    start_uid = stops[0].uid
    m_d = T.m_d_kg if opts.include_drone_mass else 0.0
    locs = [loc_of(st, n) for st in stops]
    uid_loc = {st.uid: lc for st, lc in zip(stops, locs)}

    # ---- 停車ごとの出来事 ----
    launch_at: dict[int, tuple[int, int]] = {}     # 発射する停車の uid → (客, 回収する停車の uid)
    retrieve_at: dict[int, int] = {}               # 回収する停車の uid → 客
    loops_at: dict[int, list[int]] = {}            # 往復する停車の uid → 客の列
    drone_kwh = 0.0
    for j in sorted(sol.drone):
        how = sol.drone[j]
        if isinstance(how, Loop):
            a = uid_loc[how.at]
            e, _ = T.trip(a, j, a)
            loops_at.setdefault(how.at, []).append(j)
        else:
            a, b = uid_loc[how.launch], uid_loc[how.retrieve]
            e, _ = T.trip(a, j, b)
            launch_at[how.launch] = (j, how.retrieve)
            retrieve_at[how.retrieve] = j
        if e > T.cap_b + tol:
            errors.append(f"battery exceeded for customer {j} ({e:.4f} kWh > {T.cap_b} kWh)")
        drone_kwh += e

    # ---- 積荷の初期値と容量 ----
    load = sum(prob.demand(st.ref) for st in stops if st.kind == "customer")
    for j, how in sol.drone.items():
        base_uid = how.at if isinstance(how, Loop) else how.launch
        if base_uid != start_uid:
            load += prob.demand(j)
    if load > T.Q_t + tol:
        errors.append(f"truck capacity exceeded ({load:.2f} kg > {T.Q_t} kg)")

    # ---- 出発デポ：往復 → 発射（＝出発） ----
    onboard = True
    retr_time: dict[int, float] = {}               # 回収する停車の uid → ドローンの帰着時刻
    t_dep = 0.0
    for j in loops_at.get(start_uid, []):
        t_dep += T.trip(locs[0], j, locs[0])[1]
        # 出発デポで往復する荷物は初期の積荷に入れていないので，ここでは減らさない
    if start_uid in launch_at:
        j, r_uid = launch_at[start_uid]
        retr_time[r_uid] = t_dep + T.trip(locs[0], j, uid_loc[r_uid])[1]
        onboard = False
    arrival = [0.0]
    departure = [t_dep]
    load_out = [load]
    truck_kwh = 0.0
    wait = 0.0
    depot_loop = t_dep

    # ---- 列を前からなめる ----
    for p in range(1, len(stops)):
        st = stops[p]
        a, b = locs[p - 1], locs[p]
        w = load + (m_d if onboard else 0.0)
        truck_kwh += T.truck_energy(a, b, w)
        t_arr = t_dep + T.tau[a][b]
        t_ready = t_arr
        # 到着 → 回収
        if st.uid in retrieve_at:
            if onboard:
                errors.append(f"retrieval at stop {p} while the drone is onboard")
            rt = retr_time.get(st.uid)
            if rt is None:
                errors.append(f"retrieval at stop {p} without a flight in progress")
                rt = t_arr
            if opts.forbid_drone_early and rt < t_arr - tol:
                errors.append(f"drone arrives before the truck at stop {p} (customer {retrieve_at[st.uid]})")
            t_ready = max(t_arr, rt)
            onboard = True
        # 配達（トラックの客）
        if st.kind == "customer":
            load -= prob.demand(st.ref)
        # 往復
        for j in loops_at.get(st.uid, []):
            if not onboard:
                errors.append(f"loop of customer {j} at stop {p} while the drone is away (N30)")
            t_ready += T.trip(b, j, b)[1]
            load -= prob.demand(j)
        # 発射（＝出発）
        if st.uid in launch_at:
            j, r_uid = launch_at[st.uid]
            if not onboard:
                errors.append(f"launch of customer {j} at stop {p} while the drone is away")
            retr_time[r_uid] = t_ready + T.trip(b, j, uid_loc[r_uid])[1]
            load -= prob.demand(j)
            onboard = False
        wait += t_ready - t_arr
        t_dep = t_ready
        arrival.append(t_arr)
        departure.append(t_dep)
        load_out.append(load)

    if abs(load) > tol:
        errors.append(f"load not zero at the end ({load:.6f} kg)")
    if not onboard:
        errors.append("drone not back at the end")
    completion = t_dep
    excess = 0.0 if opts.tmax_h is None else max(0.0, completion - opts.tmax_h)
    if excess <= tol:
        excess = 0.0
    obj = truck_kwh + drone_kwh + opts.lam_kwh_per_h * excess
    return Evaluation(feasible=not errors, errors=errors, truck_kwh=truck_kwh, drone_kwh=drone_kwh,
                      completion_h=completion, wait_h=wait, depot_loop_h=depot_loop, tmax_excess_h=excess,
                      objective=obj, arrival_h=arrival, departure_h=departure, load_out_kg=load_out)
