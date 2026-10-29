"""探索の確認：MILP の最適値が分かっている小さい問題を ROOST の ALNS で解き，最適値との差を見る．

対象は verify_milp.py と同じ 346 本（価値の地図 300，T_max 掃引 46）．各本を ALNS で解き，
最良解のエネルギーと MILP の最適値の差（%）を CSV に書く．

使い方（ROOST フォルダで）：
  python tools/compare_milp.py --results <NCR_MILP>/results --iterations 1000 --seeds 1 --out results/compare_milp.csv
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roost.alns import ALNSConfig, run_alns  # noqa: E402
from roost.milp_io import tmax_case, value_map_case  # noqa: E402
from roost.tables import build_tables  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, help="NCR_MILP の results フォルダ")
    ap.add_argument("--iterations", type=int, default=1000)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--out", default="results/compare_milp.csv")
    a = ap.parse_args()
    root = Path(a.results)

    cases = []
    for sub in ("ncr_value_map/value_map.csv", "ncr_value_map_n8/value_map.csv"):
        with (root / sub).open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cases.append((sub, row, *value_map_case(row)))
    with (root / "tmax_8.20.9.a/sweep.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["objective"] == "":
                continue
            cases.append(("tmax_8.20.9.a/sweep.csv", row, *tmax_case(row)))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.time()
    cache = {}
    for k, (src, row, prob, opts, _sol) in enumerate(cases, start=1):
        key = (prob.name, prob.ncr_points)
        if key not in cache:
            cache[key] = build_tables(prob)
        T = cache[key]
        opt = float(row["objective"])
        for seed in a.seeds:
            res = run_alns(prob, T, opts, ALNSConfig(iterations=a.iterations), seed=seed)
            b = res.best_eval
            e = b.energy_kwh if b is not None else float("inf")
            ncr_used = sum(1 for st in res.best.stops if st.kind == "ncr") if res.best is not None else 0
            rows.append(dict(source=src, instance=row.get("instance", "8.20.9.a"), x=row.get("x", ""),
                             y=row.get("y", ""), mode_id=row.get("mode_id", ""), tmax_min=row.get("tmax_min", ""),
                             seed=seed, iterations=a.iterations, milp_kwh=opt, roost_kwh=e,
                             gap_pct=(e / opt - 1.0) * 100.0, roost_ncr_stops=ncr_used,
                             milp_ncr_used=row.get("ncr_used", ""), runtime_s=res.runtime_s))
        if k % 25 == 0:
            print(f"{k}/{len(cases)}  {time.time() - t0:.0f}s", flush=True)

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    for src in sorted({r["source"] for r in rows}):
        g = [r["gap_pct"] for r in rows if r["source"] == src]
        print(f"{src}: {len(g)} 本  差の平均 {statistics.mean(g):+.3f}%  中央値 {statistics.median(g):+.3f}%  "
              f"最大 {max(g):+.3f}%  最適値に届いた（差 < 0.01%）{sum(x < 0.01 for x in g)} 本  "
              f"0.5% 以内 {sum(x <= 0.5 for x in g)} 本")
    worse = [r for r in rows if r["gap_pct"] < -1e-6]
    if worse:
        print(f"注意：MILP の最適値より良い解が {len(worse)} 本（評価の食い違いの疑い）")
    print(f"一覧：{out}  計 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
