"""実験 E1 の一括実行（vault/07_研究計画/ROOST実験計画_E1_20261029.md）．並列・途中再開つき．

* インスタンス：Xiao の生成器 n.d.m.a，n ∈ {20, 25, 30}，m ∈ {1..5}．
  領域の 1 辺 d は客の密度を客 8 人・20 km 四方とそろえる：d = round(20 √(n/8))（20 人 32 km，25 人 35 km，30 人 39 km）
* NCR の候補：間隔 20/6 km の格子（客 8 人の 7×7 と同じ間隔．デポの点を除く）
* 条件：(1)〜(5)．(1) は seed 1 だけ，(2)〜(5) は seed 1・2・3．5000 反復．積載上限なし（1e6 kg）
* 収束の確認：n = 30 の m = 1, 2, 3 の (2) と (5)，seed 1 を 20000 反復．同じ 3 本で (3) の最良解から (3)/(5) を 20000 反復（効果 vs 計算時間）
* phase 2：phase 1 の NCR なしの最良解から続ける 2 本立て（make_jobs の説明）
* 初期温度の係数は --t0-factor（既定 0.02．客 12 人以下は Xiao の 0.5056 のまま）
* 進み具合は progress.log と jobs.json（tools/e1_progress.py で見る）
* 1 本ごとに raw/<タグ>_result.json を書く．あるものは飛ばす（途中再開）．最後に raw/summary.csv を作り直す

使い方（ROOST フォルダで）：
  python tools/batch_e1.py --workers 5 --out results/20261029_e1
  E1b（phase 2 だけを長く）：
  python tools/batch_e1.py --workers 5 --out results/20261029_e1b --phase2-from results/20261029_e1 \
      --instances 25.35.2.a 30.39.2.a 20.32.3.a 25.35.5.a 30.39.4.a --phase2-iterations 20000
  E1c（往復なしだけ：(4) 初期解から・(2)→(4)・(2)→(2) を 20000 反復）：
  python tools/batch_e1.py --workers 5 --out results/20261029_e1c --phase2-from results/20261029_e1 \
      --instances 25.35.2.a 30.39.2.a 20.32.3.a 25.35.5.a 30.39.1.a --phase2-iterations 20000 \
      --pairs 2:2,4 --scratch-modes 4
  python tools/batch_e1.py --workers 5 --out results/20261029_e1 --dry-run   （ジョブの一覧だけ）
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import multiprocessing as mp
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import roost  # noqa: E402,F401

SPACING_KM = 20.0 / 6.0
CAPACITY_KG = 1e6
NS = (20, 25, 30)
MS = (1, 2, 3, 4, 5)


def side_km(n: int) -> int:
    return int(round(20.0 * math.sqrt(n / 8.0)))


def make_jobs(iterations: int, long_iterations: int, t0_factor: float) -> list[dict]:
    """ジョブの一覧．phase 1：初期解から．phase 2：phase 1 の NCR なしの最良解から続ける（決定 10/29）．

    phase 2 の 2 本立て（9/28 の熱海の P1a と同じ考え方）：
      (2) の最良解 → (2) のまま 5000 反復（比べる相手）／(4) で 5000 反復
      (3) の最良解 → (3) のまま 5000 反復（比べる相手）／(5) で 5000 反復
    差が「NCR を許したことで届いた改善」．探索を足した分の改善は比べる相手の側にも入る．
    """
    jobs = []
    for n in NS:
        for m in MS:
            inst = f"{n}.{side_km(n)}.{m}.a"
            stem = inst.replace(".", "-")
            for mode in (1, 2, 3, 4, 5):
                for seed in ((1,) if mode == 1 else (1, 2, 3)):
                    jobs.append(dict(instance=inst, mode=mode, seed=seed, iterations=iterations, group="scratch",
                                     phase=1, start=None, tag=f"{stem}_m{mode}_s{seed}_it{iterations}"))
            for seed in (1, 2, 3):
                for src, dsts in ((2, (2, 4)), (3, (3, 5))):
                    src_tag = f"{stem}_m{src}_s{seed}_it{iterations}"
                    for dst in dsts:
                        jobs.append(dict(instance=inst, mode=dst, seed=seed, iterations=iterations,
                                         group="continue" if dst == src else "warm", phase=2, start=src_tag,
                                         tag=f"{stem}_m{dst}_from-m{src}_s{seed}_it{iterations}"))
    for m in (1, 2, 3):
        inst = f"30.{side_km(30)}.{m}.a"
        stem = inst.replace(".", "-")
        for mode in (2, 5):
            jobs.append(dict(instance=inst, mode=mode, seed=1, iterations=long_iterations, group="convergence",
                             phase=1, start=None, tag=f"{stem}_m{mode}_s1_it{long_iterations}"))
        # 効果 vs 計算時間（10/29）：(3) の最良解から (3)/(5) を長く続ける
        src_tag = f"{stem}_m3_s1_it{iterations}"
        for dst in (3, 5):
            jobs.append(dict(instance=inst, mode=dst, seed=1, iterations=long_iterations,
                             group="continue-long" if dst == 3 else "warm-long", phase=2, start=src_tag,
                             tag=f"{stem}_m{dst}_from-m3_s1_it{long_iterations}"))
    for j in jobs:
        j["t0_factor"] = t0_factor
    return jobs


def make_jobs_phase2(instances: list[str], start_iterations: int, iterations: int, t0_factor: float,
                     start_dir: str, pairs=((2, (2, 4)), (3, (3, 5))), scratch_modes=(),
                     seeds=(1, 2, 3)) -> list[dict]:
    """E1b（10/29 夜）：選んだインスタンスだけ phase 2（continue / warm）を長く回す．
    出発点は E1 の phase 1 の最良解（start_dir の <stem>_m{2,3}_s{seed}_it{start_iterations}_best.json）．"""
    jobs = []
    for inst in instances:
        stem = inst.replace(".", "-")
        for seed in seeds:
            for mode in scratch_modes:   # 同じ反復数で初期解から（E1c：(4) を 20000 反復）
                jobs.append(dict(instance=inst, mode=mode, seed=seed, iterations=iterations, group="scratch",
                                 phase=1, start=None, t0_factor=t0_factor,
                                 tag=f"{stem}_m{mode}_s{seed}_it{iterations}"))
            for src, dsts in pairs:
                src_tag = f"{stem}_m{src}_s{seed}_it{start_iterations}"
                for dst in dsts:
                    jobs.append(dict(instance=inst, mode=dst, seed=seed, iterations=iterations,
                                     group="continue" if dst == src else "warm", phase=2, start=src_tag,
                                     start_dir=start_dir, t0_factor=t0_factor,
                                     tag=f"{stem}_m{dst}_from-m{src}_s{seed}_it{iterations}"))
    return jobs


def run_job(args) -> dict:
    job, raw_dir = args
    from roost.alns import ALNSConfig, run_alns
    from roost.milp_io import xiao_instance
    from roost.problem import from_xiao
    from roost.solution import Loop, Sortie
    from roost.tables import build_tables
    from roost.io import load_solution, save_solution
    from run_alns import MODES, ncr_candidates

    raw = Path(raw_dir)
    xi = xiao_instance(job["instance"])
    label, use_ncr, opts = MODES[job["mode"]]
    cands = ncr_candidates(xi, None, 0, 0, spacing_km=SPACING_KM)
    prob = from_xiao(xi, tuple(cands) if use_ncr else ())
    T = build_tables(prob)
    T.Q_t = CAPACITY_KG
    initial = None
    if job["start"]:
        initial, _ = load_solution(Path(job.get("start_dir") or raw) / f"{job['start']}_best.json")
    cfg = ALNSConfig(iterations=job["iterations"], t0_factor_large=job["t0_factor"])
    res = run_alns(prob, T, opts, cfg, seed=job["seed"], initial=initial)
    tag = job["tag"]
    b, sol = res.best_eval, res.best
    save_solution(raw / f"{tag}_best.json", prob, sol)
    with (raw / f"{tag}_history.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(res.history[0].keys()))
        w.writeheader()
        w.writerows(res.history)
    # NCR の使われ方：枠（出撃の発着点）と拠点（往復の起点）
    ncr_uids = {st.uid for st in sol.stops if st.kind == "ncr"}
    ncr_sortie_ends = sum((h.launch in ncr_uids) + (h.retrieve in ncr_uids)
                          for h in sol.drone.values() if isinstance(h, Sortie))
    ncr_loops = sum(1 for h in sol.drone.values() if isinstance(h, Loop) and h.at in ncr_uids)
    out = dict(
        tag=tag, group=job["group"], phase=job["phase"], start=job["start"] or "", t0_factor=job["t0_factor"],
        instance=job["instance"], n=prob.n, side_km=xi.grid_half_width_km,
        m=xi.scenario_m, xi=xi.xi, total_demand_kg=xi.total_demand_kg,
        n_heavy=sum(1 for j in range(1, prob.n + 1) if not T.drone_ok[j]),
        mode=job["mode"], label=label, seed=job["seed"], iterations=job["iterations"], n_ncr_candidates=prob.n_ncr,
        initial_kwh=res.initial_eval.energy_kwh, best_kwh=b.energy_kwh, truck_kwh=b.truck_kwh, drone_kwh=b.drone_kwh,
        completion_min=b.completion_h * 60, wait_min=b.wait_h * 60, depot_loop_min=b.depot_loop_h * 60,
        truck_customers=sum(1 for st in sol.stops if st.kind == "customer"),
        ncr_stops=len(ncr_uids), ncr_locations=len({st.ref for st in sol.stops if st.kind == "ncr"}),
        sorties=sum(1 for h in sol.drone.values() if isinstance(h, Sortie)),
        loops=sum(1 for h in sol.drone.values() if isinstance(h, Loop)),
        ncr_sortie_ends=ncr_sortie_ends, ncr_loops=ncr_loops,
        truck_customer_set=sorted(st.ref for st in sol.stops if st.kind == "customer"),
        last_improvement_it=max((int(h["it"]) for h in res.history if h["new_best"]), default=0),
        runtime_s=res.runtime_s, n_evals=res.n_evals,
        destroy_stats={k: dict(used=v.used, accepted=v.accepted, new_best=v.new_best) for k, v in res.destroy_stats.items()},
        repair_stats={k: dict(used=v.used, accepted=v.accepted, new_best=v.new_best) for k, v in res.repair_stats.items()},
    )
    (raw / f"{tag}_result.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--iterations", type=int, default=5000)
    ap.add_argument("--long-iterations", type=int, default=20000)
    ap.add_argument("--t0-factor", type=float, default=0.02, help="客 13 人以上の初期温度の係数（T_start = 係数 × 初期解の f）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None, help="タグにこの文字列を含むジョブだけ（試し用．例 20-32-1-a）")
    ap.add_argument("--phase2-from", default=None,
                    help="E1b：この結果フォルダ（例 results/20261029_e1）の phase 1 の最良解から phase 2 だけを回す")
    ap.add_argument("--instances", nargs="+", default=None, help="E1b：インスタンス（例 25.35.2.a 30.39.2.a）")
    ap.add_argument("--phase2-iterations", type=int, default=20000, help="E1b：phase 2 の反復")
    ap.add_argument("--pairs", default="2:2,4;3:3,5",
                    help="phase 2 の組（出発の条件:続ける条件,…;…）．E1c は 2:2,4（往復なしだけ）")
    ap.add_argument("--scratch-modes", default="", help="phase 2 と同じ反復で初期解からも回す条件（E1c は 4）")
    a = ap.parse_args()
    out = Path(a.out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    if a.phase2_from:
        pairs = tuple((int(x.split(":")[0]), tuple(int(v) for v in x.split(":")[1].split(",")))
                      for x in a.pairs.split(";") if x)
        scratch_modes = tuple(int(v) for v in a.scratch_modes.split(",") if v)
        jobs = make_jobs_phase2(a.instances, a.iterations, a.phase2_iterations, a.t0_factor,
                                str(Path(a.phase2_from) / "raw"), pairs=pairs, scratch_modes=scratch_modes)
        missing = [j["start"] for j in jobs if j["start"] and
                   not (Path(j["start_dir"]) / f"{j['start']}_best.json").exists()]
        if missing:
            sys.exit(f"出発点の解がない：{missing[:5]}")
    else:
        jobs = make_jobs(a.iterations, a.long_iterations, a.t0_factor)
    if a.only:
        jobs = [j for j in jobs if a.only in j["tag"]]
    todo = [j for j in jobs if not (raw / f"{j['tag']}_result.json").exists()]
    # 重いもの（客が多い・NCR あり・長い反復）から先に始める（最後に 1 本だけ残って待つ時間を減らす）
    # phase 2 の出発点がすべて別フォルダ（--phase2-from）なら，phase を分けず 1 つの列で回す
    one_queue = bool(a.phase2_from)
    todo.sort(key=lambda j: (0 if one_queue else j["phase"], -j["iterations"], -int(j["instance"].split(".")[0]),
                             -j["mode"]))
    print(f"jobs: {len(jobs)}（phase 1：{sum(j['phase'] == 1 for j in jobs)}，phase 2：{sum(j['phase'] == 2 for j in jobs)}），"
          f"done: {len(jobs) - len(todo)}，to do: {len(todo)}，workers: {a.workers}", flush=True)
    if a.dry_run:
        for j in todo:
            print(j["phase"], j["tag"], j["start"] or "")
        return
    meta_path = out / "meta.json"
    if not meta_path.exists():
        from run_alns import git_info
        root = Path(__file__).resolve().parents[1]
        meta_path.write_text(json.dumps(dict(
            command=" ".join(sys.argv), started=dt.datetime.now().isoformat(timespec="seconds"), python=sys.version,
            platform=platform.platform(), roost=git_info(root), xiao=git_info(Path(roost.XIAO_PATH)),
            spacing_km=SPACING_KM, capacity_kg=CAPACITY_KG, n_jobs=len(jobs)), indent=1, ensure_ascii=False),
            encoding="utf-8")
    (out / "jobs.json").write_text(json.dumps(dict(
        total=len(jobs), tags=[j["tag"] for j in jobs], phase={j["tag"]: j["phase"] for j in jobs},
        workers=a.workers), ensure_ascii=False), encoding="utf-8")
    log = (out / "progress.log").open("a", encoding="utf-8")

    def say(msg):
        line = f"[{dt.datetime.now():%m-%d %H:%M:%S}] {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    say(f"start: {len(todo)} to do / {len(jobs)} jobs, workers {a.workers}")
    t0 = time.time()
    k = 0
    with mp.Pool(a.workers) as pool:
        for phase in ((None,) if one_queue else (1, 2)):   # phase 2 は phase 1 の最良解を読むので，phase 1 が全部終わってから
            batch = [(j, str(raw)) for j in todo if phase is None or j["phase"] == phase]
            for r in pool.imap_unordered(run_job, batch):
                k += 1
                el = time.time() - t0
                eta = dt.datetime.now() + dt.timedelta(seconds=el / k * (len(todo) - k))
                say(f"{k}/{len(todo)}  {r['tag']}  best {r['best_kwh']:.3f}  ncr {r['ncr_stops']}  "
                    f"{r['runtime_s']:.0f}s  ETA {eta:%m-%d %H:%M}")
            if phase == 1:
                say("phase 1 done -> phase 2")
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(raw.glob("*_result.json"))]
    keys = [k for k in rows[0] if k not in ("destroy_stats", "repair_stats")]
    with (raw / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r = dict(r)
            r["truck_customer_set"] = " ".join(map(str, r["truck_customer_set"]))
            w.writerow(r)
    say(f"FINISHED. wrote {raw / 'summary.csv'}  ({len(rows)} rows)  total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
