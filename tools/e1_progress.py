"""E1 の進み具合を表示する（batch_e1.py が書く jobs.json・progress.log・raw/*_result.json を読むだけ）．

使い方（ROOST フォルダで）：
  python tools/e1_progress.py --out results/20261029_e1            （1 回表示）
  python tools/e1_progress.py --out results/20261029_e1 --watch 60 （60 秒ごとに更新．Ctrl+C で終了）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from collections import defaultdict
from pathlib import Path


def show(out: Path) -> None:
    jobs_p = out / "jobs.json"
    if not jobs_p.exists():
        print(f"{jobs_p} がない（まだ始まっていない）")
        return
    jobs = json.loads(jobs_p.read_text(encoding="utf-8"))
    raw = out / "raw"
    rows = []
    for p in raw.glob("*_result.json"):
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    done = {r["tag"] for r in rows}
    tot = jobs["total"]
    ph = jobs["phase"]
    d1 = sum(1 for t in done if ph.get(t) == 1)
    n1 = sum(1 for v in ph.values() if v == 1)
    d2 = sum(1 for t in done if ph.get(t) == 2)
    n2 = tot - n1
    log_p = out / "progress.log"
    lines = log_p.read_text(encoding="utf-8").splitlines() if log_p.exists() else []
    now = dt.datetime.now()
    print(f"=== E1 progress  {now:%m-%d %H:%M:%S}  ({out}) ===")
    bar = int(40 * len(done) / tot)
    print(f"[{'#' * bar}{'.' * (40 - bar)}] {len(done)}/{tot} ({100 * len(done) / tot:.1f}%)")
    print(f"phase 1: {d1}/{n1}   phase 2: {d2}/{n2}")
    if log_p.exists():
        age = time.time() - log_p.stat().st_mtime
        print(f"最後の記録から {age / 60:.1f} 分" + ("（長い：止まっていないか確認）" if age > 1800 else ""))
    eta = [l for l in lines if "ETA" in l]
    if eta:
        print("見込み終了:", eta[-1].split("ETA")[-1].strip(), "（phase 2 は 1 本が軽めなので前後する）")
    if any("FINISHED" in l for l in lines):
        print("*** 完了 ***")
    print("\n--- 最近の 8 件 ---")
    for l in lines[-8:]:
        print(l)
    # 途中の集計：インスタンス × 条件の平均（終わった分だけ）
    agg = defaultdict(list)
    for r in rows:
        key = (r["instance"], f"m{r['mode']}" if r["group"] == "scratch" else
               f"m{r['mode']}<-m{r['start'].split('_m')[1][0]}" if r["group"] in ("continue", "warm") else None)
        if key[1]:
            agg[key].append(r["best_kwh"])
    if agg:
        cols = ["m1", "m2", "m3", "m4", "m5", "m2<-m2", "m4<-m2", "m3<-m3", "m5<-m3"]
        print("\n--- 最良値の平均 [kWh]（終わった seed だけ．(件数)） ---")
        print(f"{'instance':<11}" + "".join(f"{c:>12}" for c in cols))
        for inst in sorted({k[0] for k in agg}, key=lambda s: tuple(map(int, s.split('.')[:3]))):
            cells = []
            for c in cols:
                v = agg.get((inst, c))
                cells.append(f"{sum(v) / len(v):8.2f}({len(v)})" if v else f"{'-':>12}")
            print(f"{inst:<11}" + "".join(f"{c:>12}" for c in cells))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/20261029_e1")
    ap.add_argument("--watch", type=int, default=0, help="この秒数ごとに更新（0 なら 1 回だけ）")
    a = ap.parse_args()
    out = Path(a.out)
    while True:
        if a.watch:
            os.system("cls" if os.name == "nt" else "clear")
        show(out)
        if not a.watch:
            break
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
