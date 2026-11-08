"""E2 の一覧 CSV と NCR の価値の集計表を作る（2026-11-08）．

使い方（ROOST フォルダで）
  python tools/e2_tables.py --out results/20261105_e2 --seeds 1 2
出力：results/20261105_e2/analysis_s12/（--seeds 3 なら analysis_s3/）
  E2_jobs_s12.csv           1 ジョブ 1 行（result.json の数値と，舞台の特徴）
  E2_ncr_value_s12.csv      1 舞台・seed・比較 1 行（NCR あり と NCR なし の差）
  E2_ncr_value_summary_s12.csv  比較×客数×地形×電池 ごとの要約
既定は seed 1・2 だけ（seed 3 は検証用．仮説を書いてから --seeds 3 で作る）．
"""


from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

TERRAINS = ("flat", "slope", "undul", "atami")
BATTERIES = ("b150", "b030")
TMAX = ("T1000", "T0975", "T0950", "T0925", "T0900", "T0875", "T0850", "T0800")

# 比較：(名前, NCR あり の手順, NCR なし の手順)
COMPARISONS = [("noloop", "m4_from-m2", "m2_from-m2"),
               ("loop", "m5_from-m3", "m3_from-m3")]
COMPARISONS += [(f"noloop_{t}", f"m4_from-m2_{t}", f"m2_from-m2_{t}") for t in TMAX]

SCALARS = ["tag", "stage", "layout", "n", "terrain", "battery", "battery_kwh", "seed", "mode", "label", "group",
           "phase", "start", "tmax_ratio", "tmax_min", "iterations", "feasible_found", "best_kwh", "truck_kwh",
           "drone_kwh", "completion_min", "wait_min", "depot_loop_min", "truck_customers", "ncr_stops",
           "ncr_locations", "sorties", "loops", "ncr_sortie_ends", "ncr_loops", "initial_kwh", "runtime_s",
           "n_evals", "last_improvement_it", "n_heavy", "total_demand_kg", "n_ncr_candidates"]

DIFF_KEYS = ["truck_kwh", "drone_kwh", "completion_min", "wait_min", "truck_customers", "ncr_stops", "sorties",
             "loops"]


def stage_features(st: dict) -> dict:
    cust = np.array(st["customers"], dtype=float)
    ok = np.array(st["drone_ok"], dtype=bool)
    reach = np.array(st["loop_reachable_from"], dtype=float)
    dep = np.array(st["depot"], dtype=float)
    dist = np.hypot(cust[:, 0] - dep[0], cust[:, 1] - dep[1])
    return {
        "n_drone_ok": int(ok.sum()),
        "n_drone_ok_no_loop": int((ok & (reach == 0)).sum()),   # ドローンで運べるが往復できる NCR 候補がない客
        "loop_reach_mean": float(reach[ok].mean()) if ok.any() else float("nan"),
        "cust_z_mean": float(cust[:, 2].mean()),
        "cust_z_max": float(cust[:, 2].max()),
        "cust_dist_mean_km": float(dist.mean()),
        "terrain_z_max": float(st["terrain_z_max"]),
    }


def main(src: Path, dst: Path, SEEDS: tuple, tag: str) -> None:
    stages = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((src / "stages").glob("*.json"))}
    feats = {k: stage_features(v) for k, v in stages.items()}

    # ---- 1. 一覧 ----
    jobs = {}
    rows = []
    for p in sorted((src / "raw").glob("*_result.json")):
        if not any(p.name.endswith(f"_s{s}_result.json") for s in SEEDS):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d["seed"] not in SEEDS:
            continue
        r = {k: d.get(k, "") for k in SCALARS}
        r["ncr_refs"] = ";".join(map(str, d.get("ncr_refs") or []))
        r["truck_customer_set"] = ";".join(map(str, d.get("truck_customer_set") or []))
        for grp in ("destroy_stats", "repair_stats"):
            for op, s in (d.get(grp) or {}).items():
                for k in ("used", "accepted", "new_best"):
                    r[f"{grp[:-6]}_{op}_{k}"] = s.get(k, "")
        r.update(feats[d["stage"]])
        rows.append(r)
        jobs[d["tag"]] = d
    if not rows:
        sys.exit(f"seed {SEEDS} の result.json が {src / 'raw'} にない")
    dst.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(dst / f"E2_jobs_{tag}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    # ---- 2. 舞台・seed・比較ごとの NCR の価値 ----
    vrows = []
    for stg, st in stages.items():
        for seed in SEEDS:
            for cname, a, b in COMPARISONS:
                ja = jobs.get(f"{stg}_{a}_s{seed}")
                jb = jobs.get(f"{stg}_{b}_s{seed}")
                if ja is None or jb is None:
                    continue
                fa, fb = bool(ja["feasible_found"]), bool(jb["feasible_found"])
                if fa and fb:
                    status = "both"
                elif fa:
                    status = "rescued"          # NCR なしでは T_max を守れず，NCR ありでは守れた
                elif fb:
                    status = "ncr_only_fail"    # 逆（あれば探索の失敗）
                else:
                    status = "both_fail"
                r = {"stage": stg, "n": ja["n"], "layout": ja["layout"], "terrain": ja["terrain"],
                     "battery": ja["battery"], "seed": seed, "comparison": cname,
                     "tmax_ratio": ja.get("tmax_ratio", ""), "status": status,
                     "kwh_without": jb["best_kwh"] if fb else "", "kwh_with": ja["best_kwh"] if fa else ""}
                r["value_pct"] = (ja["best_kwh"] - jb["best_kwh"]) / jb["best_kwh"] * 100 if status == "both" else ""
                for k in DIFF_KEYS:
                    r[f"{k}_without"] = jb.get(k, "") if fb else ""
                    r[f"{k}_with"] = ja.get(k, "") if fa else ""
                    r[f"d_{k}"] = (ja[k] - jb[k]) if status == "both" else ""
                r["n_heavy"] = ja["n_heavy"]
                r.update(feats[stg])
                vrows.append(r)
    vkeys = list(vrows[0].keys())
    with open(dst / f"E2_ncr_value_{tag}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=vkeys)
        w.writeheader()
        w.writerows(vrows)

    # ---- 3. 要約 ----
    srows = []
    for cname, _, _ in COMPARISONS:
        for n in (20, 25):
            for bat in BATTERIES:
                for ter in TERRAINS:
                    g = [r for r in vrows if r["comparison"] == cname and r["n"] == n
                         and r["battery"] == bat and r["terrain"] == ter]
                    v = np.array([r["value_pct"] for r in g if r["status"] == "both"], dtype=float)
                    s = {"comparison": cname, "n": n, "battery": bat, "terrain": ter, "count": len(g),
                         "comparable": len(v),
                         "rescued": sum(r["status"] == "rescued" for r in g),
                         "both_fail": sum(r["status"] == "both_fail" for r in g),
                         "ncr_only_fail": sum(r["status"] == "ncr_only_fail" for r in g)}
                    if len(v):
                        s.update({"value_median": np.median(v), "value_q25": np.percentile(v, 25),
                                  "value_q75": np.percentile(v, 75), "value_min": v.min(), "value_max": v.max(),
                                  "value_mean": v.mean(), "n_positive": int((v > 0).sum())})
                        for k in DIFF_KEYS:
                            dk = np.array([r[f"d_{k}"] for r in g if r["status"] == "both"], dtype=float)
                            s[f"d_{k}_median"] = np.median(dk)
                    srows.append(s)
    skeys = list(dict.fromkeys(k for r in srows for k in r))
    with open(dst / f"E2_ncr_value_summary_{tag}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=skeys)
        w.writeheader()
        for r in srows:
            w.writerow({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
    print(len(rows), "jobs,", len(vrows), "pairs,", len(srows), "summary rows")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/20261105_e2", help="結果フォルダ（raw/ と stages/ がある所）")
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2])
    a = ap.parse_args()
    tag = "s" + "".join(map(str, a.seeds))
    res = Path(a.out)
    main(res, res / f"analysis_{tag}", tuple(a.seeds), tag)
