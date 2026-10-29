"""ROOST の ALNS で Xiao (2024) 型のインスタンスを解き，結果フォルダに書き出す．

使い方（ROOST フォルダで）：
  python tools/run_alns.py --instance 20.20.1.a --ncr-grid 7 --iterations 5000 --seeds 1 2 3 --name n20-grid7
  python tools/run_alns.py --instance 8.20.9.a --ncr-grid 7 --modes 2 3 4 5 --iterations 2000 --seeds 1 2 3

* NCR の候補：--ncr-grid k なら Xiao の領域（1 辺 d，中心がデポ）を k×k の格子に切った点（デポと同じ点は除く）．
  標高は Xiao の地形関数（式 B2）．--ncr-random m なら領域に一様乱数で m 点（NCR_MILP の from_xiao と同じ乱数）
* 条件（--modes）：NCR_MILP の比較の段と同じ番号
    1 NCR なし・トラックのみ，2 NCR なし・往復なし，3 NCR なし・往復あり，4 NCR あり・往復なし，5 NCR あり・往復あり
* --tmax-min で完了時刻の上限 [分]．--max-visits で同じ NCR の地点に止まれる回数の上限（既定は上限なし）
* トラックは 1 台．需要の合計がトラックの積載上限（300 kg）を超えるインスタンスは解けない．
  --capacity-kg で上限を変えられるが，Xiao のモデルとは別物になるので結果フォルダの README に必ず書くこと

出力（Research の「実験結果の約束」）：results/YYYYMMDD_名前/
  README.md    人が書く欄（目的・仮説・反証条件）と，自動で書く結果の要約
  meta.json    ROOST・XIAO の commit と未コミットの変更の有無，コマンド，時刻，環境，seed
  config.yaml  使った条件
  raw/         summary.csv（条件 × seed ごとの値），<条件>_s<seed>_best.json（最良解），<条件>_s<seed>_history.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import platform
import random
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import roost  # noqa: E402,F401
from xiao.instance import terrain_height_m  # noqa: E402

from roost.alns import ALNSConfig, run_alns  # noqa: E402
from roost.milp_io import xiao_instance  # noqa: E402
from roost.moves import SearchParams  # noqa: E402
from roost.problem import Options, Point, from_xiao  # noqa: E402
from roost.solution import Loop  # noqa: E402
from roost.tables import build_tables  # noqa: E402

MODES = {
    1: ("m1_truck_only", False, Options(drones_enabled=False, allow_loops=False, depot_loops=False,
                                       include_drone_mass=False)),
    2: ("m2_no_ncr_no_loop", False, Options(allow_loops=False, depot_loops=False)),
    3: ("m3_no_ncr_loop", False, Options(allow_loops=True, depot_loops=True)),
    4: ("m4_ncr_no_loop", True, Options(allow_loops=False, depot_loops=False)),
    5: ("m5_ncr_loop", True, Options(allow_loops=True, depot_loops=True)),
}


def ncr_candidates(xi, grid: int | None, n_random: int | None, seed: int) -> list[Point]:
    centers = [(xi.nodes[i].x_km, xi.nodes[i].y_km) for i in xi.customers]
    half = (xi.grid_half_width_km / 2.0 if xi.coord_mode == "side" else xi.grid_half_width_km) * xi.coord_scale
    pts = []
    if grid:
        for a in range(grid):
            for b in range(grid):
                x = -half + 2 * half * a / (grid - 1)
                y = -half + 2 * half * b / (grid - 1)
                if abs(x) < 1e-9 and abs(y) < 1e-9:
                    continue   # デポと同じ点（デポ発・デポ着の出撃の抜け道になる．実験A の注意）
                pts.append(Point(x, y, terrain_height_m(x, y, centers, xi.xi)))
    if n_random:
        rng = random.Random(f"ncr_milp|xiao|{xi.name}|seed={seed}")   # NCR_MILP の from_xiao と同じ乱数
        for _ in range(n_random):
            x, y = rng.uniform(-half, half), rng.uniform(-half, half)
            pts.append(Point(x, y, terrain_height_m(x, y, centers, xi.xi)))
    return pts


def git_info(path: Path) -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception as e:   # git がない環境でも止めない
            return f"error: {e}"
    return dict(path=str(path), commit=run("rev-parse", "HEAD"), branch=run("rev-parse", "--abbrev-ref", "HEAD"),
                dirty=bool(run("status", "--porcelain")))


def solution_json(prob, sol) -> dict:
    stops = [dict(uid=st.uid, kind=st.kind, ref=st.ref) for st in sol.stops]
    drone = {}
    for j, how in sorted(sol.drone.items()):
        drone[str(j)] = dict(type="loop", at=how.at) if isinstance(how, Loop) else \
            dict(type="sortie", launch=how.launch, retrieve=how.retrieve)
    return dict(stops=stops, drone=drone,
                ncr_points=[dict(ell=ell, x_km=p.x_km, y_km=p.y_km, z_m=p.z_m) for ell, p in enumerate(prob.ncr_points)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True, help='Xiao 型の名前 "n.d.m.h"（例 20.20.1.a）')
    ap.add_argument("--ncr-grid", type=int, default=7)
    ap.add_argument("--ncr-random", type=int, default=0)
    ap.add_argument("--modes", type=int, nargs="+", default=[5])
    ap.add_argument("--iterations", type=int, default=5000)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--tmax-min", type=float, default=None)
    ap.add_argument("--max-visits", type=int, default=None)
    ap.add_argument("--capacity-kg", type=float, default=None, help="トラックの積載上限を変える（Xiao のモデルとは別物）")
    ap.add_argument("--phase2-scope", choices=["all", "inserted"], default="all")
    ap.add_argument("--name", default=None, help="結果フォルダの名前（日付の後ろ．半角英数字とハイフン）")
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--log-every", type=int, default=500)
    a = ap.parse_args()

    xi = xiao_instance(a.instance)
    cands = ncr_candidates(xi, a.ncr_grid, a.ncr_random, seed=0)
    name = a.name or f"{a.instance.replace('.', '-')}-alns"
    out = Path(a.results_dir) / f"{dt.date.today():%Y%m%d}_{name}"
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    cfg = ALNSConfig(iterations=a.iterations)
    sp = SearchParams(phase2_scope=a.phase2_scope)

    root = Path(__file__).resolve().parents[1]
    meta = dict(command=" ".join(sys.argv), started=dt.datetime.now().isoformat(timespec="seconds"),
                python=sys.version, platform=platform.platform(), roost=git_info(root),
                xiao=git_info(Path(roost.XIAO_PATH)), seeds=a.seeds)
    total_demand = xi.total_demand_kg

    summary = []
    for m in a.modes:
        label, use_ncr, opts = MODES[m]
        opts = replace(opts, tmax_h=None if a.tmax_min is None else a.tmax_min / 60.0, max_visits=a.max_visits)
        prob = from_xiao(xi, tuple(cands) if use_ncr else ())
        T = build_tables(prob)
        if a.capacity_kg is not None:
            T.Q_t = a.capacity_kg
        if total_demand > T.Q_t:
            raise SystemExit(f"需要の合計 {total_demand:.1f} kg がトラックの積載上限 {T.Q_t:.0f} kg を超える（1 台では解けない）．"
                             f"--capacity-kg を使うか，客の少ないインスタンスにする")
        for seed in a.seeds:
            print(f"[{dt.datetime.now():%H:%M:%S}] {a.instance} {label} seed {seed}", flush=True)
            res = run_alns(prob, T, opts, cfg, sp, seed=seed, log_every=a.log_every)
            b = res.best_eval
            tag = f"{label}_s{seed}"
            if res.best is not None:
                (raw / f"{tag}_best.json").write_text(json.dumps(solution_json(prob, res.best), indent=1),
                                                      encoding="utf-8")
            with (raw / f"{tag}_history.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(res.history[0].keys()))
                w.writeheader()
                w.writerows(res.history)
            row = dict(
                instance=a.instance, mode=m, label=label, seed=seed, iterations=a.iterations,
                n_customers=prob.n, n_ncr_candidates=prob.n_ncr, tmax_min=a.tmax_min, max_visits=a.max_visits,
                capacity_kg=T.Q_t, initial_kwh=res.initial_eval.energy_kwh,
                best_kwh=b.energy_kwh if b else "", truck_kwh=b.truck_kwh if b else "",
                drone_kwh=b.drone_kwh if b else "", completion_min=b.completion_h * 60 if b else "",
                wait_min=b.wait_h * 60 if b else "",
                truck_stops=sum(1 for st in res.best.stops if st.kind == "customer") if res.best else "",
                ncr_stops=sum(1 for st in res.best.stops if st.kind == "ncr") if res.best else "",
                sorties=sum(1 for h in res.best.drone.values() if not isinstance(h, Loop)) if res.best else "",
                loops=sum(1 for h in res.best.drone.values() if isinstance(h, Loop)) if res.best else "",
                runtime_s=res.runtime_s, n_evals=res.n_evals,
            )
            summary.append(row)
            print(f"    best {row['best_kwh']}  ncr {row['ncr_stops']}  {res.runtime_s:.1f}s", flush=True)

    with (raw / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    meta["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = [f"instance: {a.instance}", f"xi: {xi.xi}", f"n_customers: {xi.n_customers}",
             f"total_demand_kg: {total_demand}", f"ncr_grid: {a.ncr_grid}", f"ncr_random: {a.ncr_random}",
             f"n_ncr_candidates: {len(cands)}", f"modes: {a.modes}", f"iterations: {a.iterations}",
             f"seeds: {a.seeds}", f"tmax_min: {a.tmax_min}", f"max_visits: {a.max_visits}",
             f"capacity_kg: {a.capacity_kg}", f"phase2_scope: {a.phase2_scope}"]
    lines += [f"alns.{k}: {v}" for k, v in asdict(cfg).items()]
    lines += [f"search.{k}: {v}" for k, v in asdict(sp).items()]
    (out / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    readme = out / "README.md"
    if not readme.exists():
        res_lines = "\n".join(
            f"| {r['label']} | {r['seed']} | {r['best_kwh']:.4f} | {r['completion_min']:.1f} | {r['ncr_stops']} | "
            f"{r['sorties']} | {r['loops']} | {r['runtime_s']:.0f} |" if r["best_kwh"] != "" else
            f"| {r['label']} | {r['seed']} | 解なし | | | | | {r['runtime_s']:.0f} |" for r in summary)
        readme.write_text(f"""# {out.name}

## 目的（人が書く）

## 仮説・反証条件（人が書く）

## 条件

`config.yaml` を参照．インスタンス {a.instance}（客 {xi.n_customers} 人，ξ = {xi.xi:.1f}，需要の合計 {total_demand:.1f} kg），
NCR の候補 {len(cands)} 点，反復 {a.iterations}．{'**トラックの積載上限を ' + str(a.capacity_kg) + ' kg に変えている（Xiao のモデルとは別物）**' if a.capacity_kg else ''}

## 結果（自動）

| 条件 | seed | 総エネルギー [kWh] | 完了 [分] | NCR の停車 | 出撃 | 往復 | 時間 [s] |
|---|---|---|---|---|---|---|---|
{res_lines}

## 解釈（人が書く．数値はこのフォルダを参照し，vault には写さない）
""", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
