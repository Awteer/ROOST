"""評価器の照合：NCR_MILP の最適解を ROOST の評価器にかけ，値が一致するかを見る．

探索は回さない．MILP が出した解（route・sorties・loops）をそのまま ROOST の解に直して評価し，
MILP の目的の値・独立の検算器 check.py の値（CSV の check 列）・内訳・完了時刻と比べる．

使い方（ROOST フォルダで）：
  python tools/verify_milp.py --results <NCR_MILP>/results --out results/verify_milp.csv
  （<NCR_MILP>/results の下の ncr_value_map/value_map.csv，ncr_value_map_n8/value_map.csv，
    tmax_8.20.9.a/sweep.csv を読む）
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roost.evaluate import evaluate  # noqa: E402
from roost.milp_io import tmax_case, value_map_case  # noqa: E402
from roost.tables import build_tables  # noqa: E402


def rel_diff(a: float, b: float) -> float:
    return abs(a - b) / max(1.0, abs(b))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, help="NCR_MILP の results フォルダ")
    ap.add_argument("--out", default="results/verify_milp.csv")
    ap.add_argument("--tol", type=float, default=1e-6, help="相対誤差の許容（分母は max(1, |値|)）")
    a = ap.parse_args()
    root = Path(a.results)

    cases = []   # (出典, 行, 問題, 設定, 解)
    for sub in ("ncr_value_map/value_map.csv", "ncr_value_map_n8/value_map.csv"):
        with (root / sub).open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cases.append((sub, row, *value_map_case(row)))
    with (root / "tmax_8.20.9.a/sweep.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["objective"] == "":
                continue   # 解なし・未解決の行（照合の対象外）
            cases.append(("tmax_8.20.9.a/sweep.csv", row, *tmax_case(row)))

    tables_cache = {}
    out_rows = []
    n_bad = 0
    for src, row, prob, opts, sol in cases:
        key = (prob.name, prob.ncr_points)
        if key not in tables_cache:
            tables_cache[key] = build_tables(prob)
        ev = evaluate(prob, tables_cache[key], sol, opts)
        milp_obj = float(row["objective"])
        chk = float(row["check"])
        truck, drone = float(row["truck_kwh"]), float(row["drone_kwh"])
        comp_h = float(row["completion_h"]) if "completion_h" in row else float(row["completion_min"]) / 60.0
        d_obj = rel_diff(ev.energy_kwh, milp_obj)
        d_chk = rel_diff(ev.energy_kwh, chk)
        d_tr = rel_diff(ev.truck_kwh, truck)
        d_dr = rel_diff(ev.drone_kwh, drone)
        d_ct = abs(ev.completion_h - comp_h) * 60.0   # 分
        d_wait = ""
        if "wait_min" in row and row["wait_min"] != "":
            d_wait = abs(ev.wait_h * 60.0 - float(row["wait_min"]))
        ok = (ev.feasible and ev.within_tmax and max(d_obj, d_chk, d_tr, d_dr) <= a.tol and d_ct <= a.tol * 60
              and (d_wait == "" or d_wait <= a.tol * 60))
        n_bad += not ok
        out_rows.append(dict(
            source=src, instance=row.get("instance", "8.20.9.a"), x=row.get("x", ""), y=row.get("y", ""),
            mode_id=row.get("mode_id", ""), tmax_min=row.get("tmax_min", ""), ok=ok, feasible=ev.feasible,
            within_tmax=ev.within_tmax, errors=" | ".join(ev.errors),
            roost_kwh=ev.energy_kwh, milp_kwh=milp_obj, check_kwh=chk,
            rel_diff_milp=d_obj, rel_diff_check=d_chk, rel_diff_truck=d_tr, rel_diff_drone=d_dr,
            diff_completion_min=d_ct, diff_wait_min=d_wait,
        ))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    by_src = {}
    for r in out_rows:
        s = by_src.setdefault(r["source"], [0, 0])
        s[0] += 1
        s[1] += r["ok"]
    for src, (tot, good) in by_src.items():
        print(f"{src}: {good}/{tot} 一致")
    print(f"最大の相対誤差：MILP {max(r['rel_diff_milp'] for r in out_rows):.2e}，"
          f"check {max(r['rel_diff_check'] for r in out_rows):.2e}，"
          f"トラック {max(r['rel_diff_truck'] for r in out_rows):.2e}，"
          f"ドローン {max(r['rel_diff_drone'] for r in out_rows):.2e}，"
          f"完了時刻の差の最大 {max(r['diff_completion_min'] for r in out_rows):.2e} 分")
    waits = [r["diff_wait_min"] for r in out_rows if r["diff_wait_min"] != ""]
    if waits:
        print(f"待ちの差の最大 {max(waits):.2e} 分（tmax の行だけ）")
    print(f"不一致 {n_bad} 件．一覧：{out}")
    if n_bad:
        for r in out_rows:
            if not r["ok"]:
                print("  NG", r["source"], r["instance"], r["x"], r["y"], r["mode_id"], r["tmax_min"], r["errors"][:200])
        sys.exit(1)


if __name__ == "__main__":
    main()
