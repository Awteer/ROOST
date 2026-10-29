"""E1 の全結果の経路を PNG にする（batch_e1.py の raw/ を読む．計算はしない）．

出力（--out の下の png/）：
  <インスタンス>_s<seed>.png  … 3×3 の地図＋最良値の推移（PANELS の順に左上から）
      1 段目：(1) トラックだけ（seed 1 のもの），(2)，(3)
      2 段目：(4)，(5)，(2)→(2) continue
      3 段目：(2)→(4) warm，(3)→(3) continue，(3)→(5) warm
  <インスタンス>_long.png     … 20000 反復の 4 本（n = 30 の m = 1, 2, 3 だけ）
  --noloop のとき：noloop/<インスタンス>.png … 行 = seed 1〜3，列 = (2)，(4)，(2)→(4) warm
あるファイルは飛ばす（途中再開．描き直すときは --force）．

使い方（ROOST フォルダで）：
  python tools/plot_e1.py --out results/20261029_e1 --workers 4
  python tools/plot_e1.py --out results/20261029_e1 --only 30-39-2-a       （タグにこの文字列を含むものだけ）
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import roost  # noqa: E402,F401

# (タグの後ろ半分の作り方, 見出し)．{s} は seed，{it} は反復．
PANELS = [
    ("m1_s1_it{it}", "(1) トラックだけ"),
    ("m2_s{s}_it{it}", "(2) NCR なし・往復なし"),
    ("m3_s{s}_it{it}", "(3) NCR なし・往復あり"),
    ("m4_s{s}_it{it}", "(4) NCR あり・往復なし"),
    ("m5_s{s}_it{it}", "(5) NCR あり・往復あり"),
    ("m2_from-m2_s{s}_it{it}", "(2)→(2) continue"),
    ("m4_from-m2_s{s}_it{it}", "(2)→(4) warm"),
    ("m3_from-m3_s{s}_it{it}", "(3)→(3) continue"),
    ("m5_from-m3_s{s}_it{it}", "(3)→(5) warm"),
]
PHASE2_PANELS = PANELS[5:]   # E1b（phase 2 だけ）用
LONG_PANELS = [
    ("m2_s1_it{it}", "(2) 初期解から"),
    ("m5_s1_it{it}", "(5) 初期解から"),
    ("m3_from-m3_s1_it{it}", "(3)→(3) continue"),
    ("m5_from-m3_s1_it{it}", "(3)→(5) warm"),
]


def plot_one(args) -> str:
    stem, panels, seed, it, raw_dir, png_path, suffix = args
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    from plot_solutions import draw_map, terrain_grid
    from roost.evaluate import evaluate
    from roost.io import load_solution
    from roost.milp_io import xiao_instance
    from roost.problem import from_xiao
    from roost.tables import build_tables
    from run_alns import MODES
    from batch_e1 import CAPACITY_KG

    for f in ("Yu Gothic", "Meiryo", "Noto Sans CJK JP", "IPAexGothic", "MS Gothic"):
        if any(f in x.name for x in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break

    raw = Path(raw_dir)
    inst = stem.replace("-", ".")
    xi = xiao_instance(inst)
    half = (xi.grid_half_width_km / 2.0 if xi.coord_mode == "side" else xi.grid_half_width_km) * xi.coord_scale
    terrain = terrain_grid(xi, half)
    ncols = 3 if len(panels) > 4 else 2
    nrows = (len(panels) + ncols - 1) // ncols
    H = 7.4 * nrows + 3.2
    fig = plt.figure(figsize=(7.0 * ncols, H))
    gs = fig.add_gridspec(nrows + 1, ncols, height_ratios=[3.2] * nrows + [1.3], hspace=0.32, wspace=0.16,
                          top=1 - (1.25 if ncols == 3 else 1.6) / H, bottom=0.03)
    ax_h = fig.add_subplot(gs[nrows, :])
    for k, (pat, title) in enumerate(panels):
        ax = fig.add_subplot(gs[k // ncols, k % ncols])
        tag = f"{stem}_{pat.format(s=seed, it=it)}"
        res_p = raw / f"{tag}_result.json"
        if not res_p.exists():
            ax.text(0.5, 0.5, f"{title}\n（結果なし）", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            continue
        res = json.loads(res_p.read_text(encoding="utf-8"))
        sol, ncr = load_solution(raw / f"{tag}_best.json")
        _, use_ncr, opts = MODES[res["mode"]]
        prob = from_xiao(xi, ncr)
        T = build_tables(prob)
        T.Q_t = CAPACITY_KG
        ev = evaluate(prob, T, sol, opts)
        note = "" if ev.feasible else f"  ※評価エラー {ev.errors[:1]}"
        if abs(ev.energy_kwh - res["best_kwh"]) > 1e-6:
            note += f"  ※記録 {res['best_kwh']:.3f} と不一致"
        draw_map(ax, prob, T, sol, ev, xi, f"{title}{note}", half, terrain=terrain)
        hist_p = raw / f"{tag}_history.csv"
        if hist_p.exists():
            with hist_p.open(encoding="utf-8") as f:
                h = [(int(r["it"]), float(r["best_kwh"])) for r in csv.DictReader(f)]
            h = h[:: max(1, len(h) // 1000)] + h[-1:]
            ax_h.plot([a for a, _ in h], [b for _, b in h], label=f"{title}  {res['best_kwh']:.2f}")
    ax_h.set_xlabel("反復")
    ax_h.set_ylabel("最良の総エネルギー [kWh]")
    ax_h.grid(alpha=0.3)
    ax_h.legend(fontsize=8.5, ncol=3)
    handles = [
        Line2D([], [], marker="*", ls="", c="gold", mec="k", ms=13, label="デポ"),
        Line2D([], [], marker="o", ls="", c="#1f4e9c", mec="k", label="トラックで配る客"),
        Line2D([], [], marker="o", ls="", c="#e67e22", mec="k", label="ドローンで配る客"),
        Line2D([], [], marker="s", ls="", c="w", mec="k", label="重い客（□，トラックだけ）"),
        Line2D([], [], marker="^", ls="", c="#2ca02c", mec="k", ms=9, label="使った NCR"),
        Line2D([], [], marker=".", ls="", c="0.6", label="NCR の候補"),
        Line2D([], [], c="#1f4e9c", lw=1.6, label="トラックの経路"),
        Line2D([], [], c="#e67e22", ls="--", label="往復"),
        Line2D([], [], c="#c0392b", ls="--", label="出撃"),
    ]
    fig.legend(handles=handles, loc="upper center", ncol=9 if ncols == 3 else 5, fontsize=9.5, frameon=False, bbox_to_anchor=(0.5, 1 - 0.05 / H))
    fig.suptitle(f"{inst}{suffix}（客 {xi.n_customers} 人，{2 * half:.0f} km 四方，ξ = {xi.xi:.0f}，"
                 f"需要計 {xi.total_demand_kg:.0f} kg，背景は標高・等高線 50 m）", y=1 - (0.5 if ncols == 3 else 0.85) / H, fontsize=14)
    fig.savefig(png_path, dpi=90, bbox_inches="tight")
    plt.close(fig)
    return str(png_path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/20261029_e1")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--iterations", type=int, default=5000)
    ap.add_argument("--long-iterations", type=int, default=20000)
    ap.add_argument("--noloop-long", action="store_true",
                    help="E1c：行 = seed 1〜3，列 = (2)→(2) continue，(4) 初期解から，(2)→(4) warm（--iterations の反復）")
    ap.add_argument("--noloop", action="store_true",
                    help="往復なしだけ：行 = seed 1〜3，列 = (2)，(4)，(2)→(4) warm．png/noloop/<インスタンス>.png")
    ap.add_argument("--phase2-only", action="store_true", help="E1b：phase 2 の 4 本だけを描く（--iterations は phase 2 の反復）")
    a = ap.parse_args()
    out = Path(a.out)
    raw = out / "raw"
    png = out / "png"
    png.mkdir(exist_ok=True)
    tags = json.loads((out / "jobs.json").read_text(encoding="utf-8"))["tags"]
    stems = sorted({t.split("_m")[0] for t in tags}, key=lambda s: tuple(map(int, s.split("-")[:3])))
    tasks = []
    if a.noloop:
        png = png / "noloop"
        png.mkdir(exist_ok=True)
    for stem in stems:
        if a.noloop_long:
            panels = []
            for sd in (1, 2, 3):
                panels += [(f"m2_from-m2_s{sd}_it{{it}}", f"(2)→(2) continue，seed {sd}"),
                           (f"m4_s{sd}_it{{it}}", f"(4) 初期解から，seed {sd}"),
                           (f"m4_from-m2_s{sd}_it{{it}}", f"(2)→(4) warm，seed {sd}")]
            tasks.append((stem, panels, 0, a.iterations, str(raw), png / f"{stem}.png",
                          f"，往復なし {a.iterations} 反復"))
            continue
        if a.noloop:
            panels = []
            for sd in (1, 2, 3):
                panels += [(f"m2_s{sd}_it{{it}}", f"(2) NCR なし・往復なし，seed {sd}"),
                           (f"m4_s{sd}_it{{it}}", f"(4) NCR あり・往復なし，seed {sd}"),
                           (f"m4_from-m2_s{sd}_it{{it}}", f"(2)→(4) warm，seed {sd}")]
            tasks.append((stem, panels, 0, a.iterations, str(raw), png / f"{stem}.png", "，往復なし"))
            continue
        if a.phase2_only:
            for seed in (1, 2, 3):
                tasks.append((stem, PHASE2_PANELS, seed, a.iterations, str(raw), png / f"{stem}_s{seed}.png",
                              f"，seed {seed}，phase 2 {a.iterations} 反復"))
            continue
        for seed in (1, 2, 3):
            tasks.append((stem, PANELS, seed, a.iterations, str(raw), png / f"{stem}_s{seed}.png", f"，seed {seed}"))
        if any(t.startswith(stem) and t.endswith(f"_it{a.long_iterations}") for t in tags):
            tasks.append((stem, LONG_PANELS, 1, a.long_iterations, str(raw), png / f"{stem}_long.png",
                          f"，{a.long_iterations} 反復"))
    if a.only:
        tasks = [t for t in tasks if a.only in t[0]]
    todo = [t for t in tasks if a.force or not Path(t[5]).exists()]
    print(f"png: {len(tasks)}，to do: {len(todo)}，workers: {a.workers}，出力先: {png}", flush=True)
    t0 = time.time()
    with mp.Pool(a.workers) as pool:
        for k, p in enumerate(pool.imap_unordered(plot_one, todo), 1):
            print(f"{k}/{len(todo)}  {Path(p).name}  {time.time() - t0:.0f}s", flush=True)
    print(f"done: {png}")


if __name__ == "__main__":
    main()
