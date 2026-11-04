"""実験 E2：坂道都市モデル（人工地形）での一括実行．並列・途中再開つき（2026-11-04）．

目的（README_E2 に詳しく）：探索手法（NCR の選び方の評価値）を作るための素材を集める．
地形（傾き・起伏）・ドローンの届く範囲（電池）・時間の上限 T_max を 1 因子ずつ変え，
良い解で選ばれる NCR と，その価値（NCR なしで続けた解との差）を記録する．

舞台
----
* 領域：1 辺 5 km．海岸は下の辺（y = -2.5 km），デポは海岸の中央 (0, -2.5)（港）
* 客：Xiao の生成器（xiao.instance.generate_instance）で n 人・配置 m の座標と需要を作る（ξ = 0）．
  標高は地形から取る（Xiao の山の地形は使わない）
* 地形（roost.terrain．seed 2 に固定）：
    flat   平地（対照）
    slope  傾きだけ（8%）
    undul  起伏だけ（尾根＋細かい起伏．傾き 0）
    atami  熱海型（傾き＋起伏．熱海の道路ノードの統計に合わせた値）
  undul と atami は同じ乱数の起伏（atami ＝ slope ＋ undul の起伏．ただし 0 m で切る）
* トラックのエネルギーと走行時間は直線に沿って地形の上で積分する（Problem.terrain）．ドローンは両端だけ
* 電池：b150（Xiao の 1.5 kWh．往復の半径 約 10 km で全域に届く），b030（0.30 kWh．往復の半径 約 1.5〜1.8 km）
* NCR の候補：0.5 km 間隔の格子（11×11 からデポの点を除く 120 点）．標高は地形から
* トラックの積載上限なし（1e6 kg）

手順（seed ごと．seed 1 の全条件 → seed 2 → seed 3 の順．途中で止まっても全条件がそろった seed が残る）
------------------------------------------------------------------------------------------
* phase 1（初期解から）：(2) (3) (4) (5)
* phase 2（phase 1 の NCR なしの最良解から．T_max なし）：(2)→(2) (2)→(4) (3)→(3) (3)→(5)
* phase 2（T_max あり）：(2)→(2) (2)→(4) を T_max = r × T_ref，r ∈ {1.0, 0.975, 0.95, 0.925, 0.9, 0.875, 0.85}
    T_ref ＝ 同じ舞台・同じ seed の phase 1 の (2) の最良解の完了時刻
  →(2) は「探索を足しただけ」の比べる相手．→(4)・→(5) との差が「NCR を許したことで届いた改善」

使い方（ROOST フォルダで）
  python tools/batch_e2.py --out results/20261104_e2pilot --iterations 1000 --layouts 20.1 25.1 --seeds 1
  python tools/batch_e2.py --out results/20261105_e2 --iterations 5000
  python tools/batch_e2.py --out ... --dry-run     （ジョブの一覧だけ）
1 本ごとに raw/<タグ>_result.json を書く．あるものは飛ばす（途中再開）．最後に raw/summary.csv を作り直す．
舞台の地点（客・デポ・NCR の候補と標高）は stages/<舞台>.json に書く（後の解析用）．
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import multiprocessing as mp
import platform
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import roost  # noqa: E402,F401

SIDE_KM = 5.0
SPACING_KM = 0.5
CAPACITY_KG = 1e6
TERRAIN_SEED = 2
TERRAINS = {
    "flat": dict(slope=0.0, ridge_amp_m=0.0, noise_rms_m=0.0),
    "slope": dict(ridge_amp_m=0.0, noise_rms_m=0.0),
    "undul": dict(slope=0.0),
    "atami": dict(),
}
BATTERIES = {"b150": 1.5, "b030": 0.30}
LAYOUTS = tuple(f"{n}.{m}" for n in (20, 25) for m in (1, 2, 3, 4, 5))
TMAX_RATIOS = (1.0, 0.975, 0.95, 0.925, 0.9, 0.875, 0.85)   # 2026-11-05：仮実験で 0.8 は (2) が守れない舞台が多かったので細かく

_cache: dict = {}


def stage_name(layout: str, terrain: str, battery: str) -> str:
    n, m = layout.split(".")
    return f"n{n}m{m}_{terrain}_{battery}"


def terrain_obj(terrain: str):
    from roost.terrain import TerrainSpec, make_terrain
    key = ("terrain", terrain)
    if key not in _cache:
        _cache[key] = make_terrain(replace(TerrainSpec(side_km=SIDE_KM, seed=TERRAIN_SEED), **TERRAINS[terrain]))
    return _cache[key]


def build_problem(layout: str, terrain: str, use_ncr: bool):
    """舞台の問題データ（NCR の候補あり・なし）．"""
    from roost.problem import Point, Problem
    from xiao.instance import generate_instance

    key = ("prob", layout, terrain, use_ncr)
    if key in _cache:
        return _cache[key]
    n, m = (int(v) for v in layout.split("."))
    ter = terrain_obj(terrain)
    xi = generate_instance(n, SIDE_KM, m, "a", xi=0.0)      # 座標 U(-2.5, 2.5)，需要は式 (B1)
    cs = [xi.nodes[i] for i in xi.customers]
    h = lambda x, y: float(ter.height(x, y))                 # noqa: E731
    depot = Point(0.0, -SIDE_KM / 2, h(0.0, -SIDE_KM / 2))
    customers = tuple(Point(c.x_km, c.y_km, h(c.x_km, c.y_km)) for c in cs)
    ncr = ()
    if use_ncr:
        g = int(round(SIDE_KM / SPACING_KM)) + 1
        pts = []
        for a in range(g):
            for b in range(g):
                x = -SIDE_KM / 2 + SIDE_KM * a / (g - 1)
                y = -SIDE_KM / 2 + SIDE_KM * b / (g - 1)
                if abs(x - depot.x_km) < 1e-9 and abs(y - depot.y_km) < 1e-9:
                    continue   # デポと同じ点（デポ発・デポ着の出撃の抜け道になる）
                pts.append(Point(x, y, h(x, y)))
        ncr = tuple(pts)
    prob = Problem(name=f"n{n}m{m}_{terrain}", depot=depot, customers=customers,
                   demands_kg=tuple(c.demand_kg for c in cs), ncr_points=ncr, terrain=ter)
    _cache[key] = prob
    return prob


def build_T(prob, battery: str):
    from roost.tables import build_tables
    from xiao.params import EnergyParams

    key = ("T", prob.name, prob.n_ncr, battery)
    if key not in _cache:
        ep = EnergyParams()
        ep = replace(ep, drone=replace(ep.drone, battery_kwh=BATTERIES[battery]))
        T = build_tables(prob, ep)
        T.Q_t = CAPACITY_KG
        _cache[key] = T
    return _cache[key]


def make_jobs(layouts, terrains, batteries, seeds, iterations: int, t0_factor: float) -> list[dict]:
    jobs = []
    for seed in seeds:
        for lay in layouts:
            for ter in terrains:
                for bat in batteries:
                    st = stage_name(lay, ter, bat)
                    base = dict(layout=lay, terrain=ter, battery=bat, seed=seed, iterations=iterations,
                                t0_factor=t0_factor, stage=st)
                    for mode in (2, 3, 4, 5):
                        jobs.append(dict(base, mode=mode, phase=1, group="scratch", start=None, tmax_ratio=None,
                                         tag=f"{st}_m{mode}_s{seed}"))
                    for src, dst in ((2, 2), (2, 4), (3, 3), (3, 5)):
                        jobs.append(dict(base, mode=dst, phase=2, group="continue" if src == dst else "warm",
                                         start=f"{st}_m{src}_s{seed}", tmax_ratio=None,
                                         tag=f"{st}_m{dst}_from-m{src}_s{seed}"))
                    for r in TMAX_RATIOS:
                        for src, dst in ((2, 2), (2, 4)):
                            jobs.append(dict(base, mode=dst, phase=2, group="continue" if src == dst else "warm",
                                             start=f"{st}_m{src}_s{seed}", tmax_ratio=r,
                                             tag=f"{st}_m{dst}_from-m{src}_T{int(round(r * 1000)):04d}_s{seed}"))
    return jobs


def run_job(args) -> dict:
    job, raw_dir = args
    from roost.alns import ALNSConfig, run_alns
    from roost.io import load_solution, save_solution
    from roost.solution import Loop, Sortie
    from run_alns import MODES

    raw = Path(raw_dir)
    label, use_ncr, opts = MODES[job["mode"]]
    prob = build_problem(job["layout"], job["terrain"], use_ncr)
    T = build_T(prob, job["battery"])
    tmax_min = None
    if job["tmax_ratio"] is not None:
        ref = json.loads((raw / f"{job['start']}_result.json").read_text(encoding="utf-8"))
        tmax_min = job["tmax_ratio"] * ref["completion_min"]
        opts = replace(opts, tmax_h=tmax_min / 60.0)
    initial = None
    if job["start"]:
        initial, _ = load_solution(raw / f"{job['start']}_best.json")
    cfg = ALNSConfig(iterations=job["iterations"], t0_factor_large=job["t0_factor"])
    res = run_alns(prob, T, opts, cfg, seed=job["seed"], initial=initial)
    tag = job["tag"]
    with (raw / f"{tag}_history.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(res.history[0].keys()))
        w.writeheader()
        w.writerows(res.history)
    out = dict(
        tag=tag, stage=job["stage"], layout=job["layout"], terrain=job["terrain"], battery=job["battery"],
        battery_kwh=BATTERIES[job["battery"]], group=job["group"], phase=job["phase"], start=job["start"] or "",
        tmax_ratio="" if job["tmax_ratio"] is None else job["tmax_ratio"],
        tmax_min="" if tmax_min is None else tmax_min, t0_factor=job["t0_factor"],
        n=prob.n, total_demand_kg=sum(prob.demands_kg),
        n_heavy=sum(1 for j in range(1, prob.n + 1) if not T.drone_ok[j]),
        mode=job["mode"], label=label, seed=job["seed"], iterations=job["iterations"],
        n_ncr_candidates=prob.n_ncr, initial_kwh=res.initial_eval.energy_kwh,
        runtime_s=res.runtime_s, n_evals=res.n_evals,
        destroy_stats={k: dict(used=v.used, accepted=v.accepted, new_best=v.new_best) for k, v in res.destroy_stats.items()},
        repair_stats={k: dict(used=v.used, accepted=v.accepted, new_best=v.new_best) for k, v in res.repair_stats.items()},
    )
    if res.best is None:
        # T_max を守った解が一度も見つからなかった（守れない T_max の可能性）
        out.update(feasible_found=False, best_kwh="", truck_kwh="", drone_kwh="", completion_min="", wait_min="",
                   depot_loop_min="", truck_customers="", ncr_stops="", ncr_locations="", ncr_refs=[],
                   sorties="", loops="", ncr_sortie_ends="", ncr_loops="", truck_customer_set=[],
                   last_improvement_it="")
    else:
        b, sol = res.best_eval, res.best
        save_solution(raw / f"{tag}_best.json", prob, sol)
        ncr_uids = {st.uid for st in sol.stops if st.kind == "ncr"}
        out.update(
            feasible_found=True, best_kwh=b.energy_kwh, truck_kwh=b.truck_kwh, drone_kwh=b.drone_kwh,
            completion_min=b.completion_h * 60, wait_min=b.wait_h * 60, depot_loop_min=b.depot_loop_h * 60,
            truck_customers=sum(1 for st in sol.stops if st.kind == "customer"),
            ncr_stops=len(ncr_uids), ncr_locations=len({st.ref for st in sol.stops if st.kind == "ncr"}),
            ncr_refs=sorted({st.ref for st in sol.stops if st.kind == "ncr"}),
            sorties=sum(1 for h in sol.drone.values() if isinstance(h, Sortie)),
            loops=sum(1 for h in sol.drone.values() if isinstance(h, Loop)),
            ncr_sortie_ends=sum((h.launch in ncr_uids) + (h.retrieve in ncr_uids)
                                for h in sol.drone.values() if isinstance(h, Sortie)),
            ncr_loops=sum(1 for h in sol.drone.values() if isinstance(h, Loop) and h.at in ncr_uids),
            truck_customer_set=sorted(st.ref for st in sol.stops if st.kind == "customer"),
            last_improvement_it=max((int(h["it"]) for h in res.history if h["new_best"]), default=0),
        )
    (raw / f"{tag}_result.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def write_stages(out: Path, layouts, terrains, batteries) -> None:
    """舞台ごとに地点と，ドローンで届く客の情報を書く（解析用）．"""
    d = out / "stages"
    d.mkdir(parents=True, exist_ok=True)
    for lay in layouts:
        for ter in terrains:
            prob = build_problem(lay, ter, True)
            for bat in batteries:
                p = d / f"{stage_name(lay, ter, bat)}.json"
                if p.exists():
                    continue
                T = build_T(prob, bat)
                # 客 j を，地点 a からの往復で電池の範囲内に届けられる地点の数（デポ・客・候補）
                reach = {}
                for j in range(1, prob.n + 1):
                    if not T.drone_ok[j]:
                        reach[j] = 0
                        continue
                    reach[j] = sum(1 for a in range(prob.n_locations)
                                   if a != j and T.trip(a, j, a)[0] <= T.cap_b + 1e-12)
                pt = lambda q: [q.x_km, q.y_km, q.z_m]   # noqa: E731
                p.write_text(json.dumps(dict(
                    stage=stage_name(lay, ter, bat), layout=lay, terrain=ter, battery=bat,
                    battery_kwh=BATTERIES[bat], side_km=SIDE_KM, spacing_km=SPACING_KM, terrain_seed=TERRAIN_SEED,
                    depot=pt(prob.depot), customers=[pt(c) for c in prob.customers], demands_kg=list(prob.demands_kg),
                    ncr_points=[pt(c) for c in prob.ncr_points],
                    drone_ok=[bool(T.drone_ok[j]) for j in range(1, prob.n + 1)],
                    loop_reachable_from=[reach[j] for j in range(1, prob.n + 1)],
                    terrain_z_max=float(prob.terrain.z.max())), indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--iterations", type=int, default=5000)
    ap.add_argument("--t0-factor", type=float, default=0.02)
    ap.add_argument("--layouts", nargs="+", default=list(LAYOUTS), help="n.m（例 20.1 25.3）")
    ap.add_argument("--terrains", nargs="+", default=list(TERRAINS), choices=list(TERRAINS))
    ap.add_argument("--batteries", nargs="+", default=list(BATTERIES), choices=list(BATTERIES))
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    jobs = make_jobs(a.layouts, a.terrains, a.batteries, a.seeds, a.iterations, a.t0_factor)
    todo = [j for j in jobs if not (raw / f"{j['tag']}_result.json").exists()]
    print(f"jobs: {len(jobs)}, done: {len(jobs) - len(todo)}, to do: {len(todo)}, workers: {a.workers}", flush=True)
    if a.dry_run:
        for j in todo:
            print(j["seed"], j["phase"], j["tag"], j["start"] or "")
        return
    meta_path = out / "meta.json"
    if not meta_path.exists():
        from run_alns import git_info
        root = Path(__file__).resolve().parents[1]
        meta_path.write_text(json.dumps(dict(
            command=" ".join(sys.argv), started=dt.datetime.now().isoformat(timespec="seconds"), python=sys.version,
            platform=platform.platform(), roost=git_info(root), xiao=git_info(Path(roost.XIAO_PATH)),
            side_km=SIDE_KM, spacing_km=SPACING_KM, capacity_kg=CAPACITY_KG, terrain_seed=TERRAIN_SEED,
            terrains=TERRAINS, batteries=BATTERIES, tmax_ratios=TMAX_RATIOS, n_jobs=len(jobs)),
            indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "jobs.json").write_text(json.dumps(dict(
        total=len(jobs), tags=[j["tag"] for j in jobs], phase={j["tag"]: j["phase"] for j in jobs},
        workers=a.workers), ensure_ascii=False), encoding="utf-8")
    write_stages(out, a.layouts, a.terrains, a.batteries)
    root = Path(__file__).resolve().parents[1]
    readme = out / "README.md"
    if not readme.exists():
        plan = root / "docs" / "実験計画_E2_20261104.md"
        readme.write_text(plan.read_text(encoding="utf-8") if plan.exists() else "E2\n", encoding="utf-8")
    cfg_path = out / "config.yaml"
    if not cfg_path.exists():
        lines = [f"iterations: {a.iterations}", f"t0_factor: {a.t0_factor}", f"workers: {a.workers}",
                 f"layouts: [{', '.join(a.layouts)}]", f"terrains: [{', '.join(a.terrains)}]",
                 f"batteries: [{', '.join(a.batteries)}]", f"seeds: [{', '.join(map(str, a.seeds))}]",
                 f"side_km: {SIDE_KM}", f"spacing_km: {SPACING_KM}", f"capacity_kg: {CAPACITY_KG}",
                 f"terrain_seed: {TERRAIN_SEED}", f"tmax_ratios: [{', '.join(map(str, TMAX_RATIOS))}]",
                 "battery_kwh: {" + ", ".join(f"{k}: {v}" for k, v in BATTERIES.items()) + "}"]
        cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
        for seed in a.seeds:
            for phase in (1, 2):   # phase 2 は phase 1 の最良解（と T_ref）を読むので，同じ seed の phase 1 の後
                batch = [(j, str(raw)) for j in todo if j["seed"] == seed and j["phase"] == phase]
                batch.sort(key=lambda x: (-int(x[0]["layout"].split(".")[0]), -x[0]["mode"]))   # 重いものから
                for r in pool.imap_unordered(run_job, batch):
                    k += 1
                    el = time.time() - t0
                    eta = dt.datetime.now() + dt.timedelta(seconds=el / k * (len(todo) - k))
                    best = f"{r['best_kwh']:.3f}" if r["feasible_found"] else "none"
                    say(f"{k}/{len(todo)}  {r['tag']}  best {best}  ncr {r['ncr_stops']}  "
                        f"{r['runtime_s']:.0f}s  ETA {eta:%m-%d %H:%M}")
                say(f"seed {seed} phase {phase} done")
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(raw.glob("*_result.json"))]
    keys = [k for k in rows[0] if k not in ("destroy_stats", "repair_stats")]
    for r in rows:
        for kk in r:
            if kk not in keys and kk not in ("destroy_stats", "repair_stats"):
                keys.append(kk)
    with (raw / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r = dict(r)
            r["truck_customer_set"] = " ".join(map(str, r["truck_customer_set"]))
            r["ncr_refs"] = " ".join(map(str, r["ncr_refs"]))
            w.writerow(r)
    say(f"FINISHED. wrote {raw / 'summary.csv'}  ({len(rows)} rows)  total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
