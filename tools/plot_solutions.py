"""ROOST の解を地図に描いて並べる（run_alns.py の結果フォルダの *_best.json と *_history.csv を読む）．

使い方（ROOST フォルダで）：
  python tools/plot_solutions.py --instance 30.39.1.a --runs results/A/raw/m4_ncr_no_loop_s1 results/B/raw/m5_ncr_loop_s1 \
      --titles "(4) NCR あり・往復なし" "(5) NCR あり・往復あり" --out compare.png

--runs は「*_best.json と *_history.csv の共通の頭」（拡張子と _best / _history を除いた部分）．
上の段：地図（背景は Xiao の地形の標高，等高線 50 m）．下の段：最良値の推移．
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

import roost  # noqa: E402,F401
from xiao.instance import terrain_height_m  # noqa: E402

from roost.evaluate import evaluate  # noqa: E402
from roost.milp_io import xiao_instance  # noqa: E402
from roost.problem import Options, Point, from_xiao  # noqa: E402
from roost.solution import Loop, Solution, Sortie, Stop  # noqa: E402
from roost.tables import build_tables  # noqa: E402

for _f in ("Noto Sans CJK JP", "IPAexGothic", "Yu Gothic", "Meiryo", "MS Gothic"):
    if any(_f in f.name for f in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = _f
        break


def load_run(prefix: str):
    best = json.loads(Path(prefix + "_best.json").read_text(encoding="utf-8"))
    hist_path = Path(prefix + "_history.csv")
    hist = list(csv.DictReader(hist_path.open(encoding="utf-8"))) if hist_path.exists() else []
    stops = [Stop(uid=s["uid"], kind=s["kind"], ref=s["ref"]) for s in best["stops"]]
    drone = {}
    for j, d in best["drone"].items():
        drone[int(j)] = Loop(d["at"]) if d["type"] == "loop" else Sortie(d["launch"], d["retrieve"])
    ncr = tuple(Point(p["x_km"], p["y_km"], p["z_m"]) for p in best["ncr_points"])
    return Solution(stops=stops, drone=drone), ncr, hist


def draw_map(ax, prob, T, sol, ev, xi, title, half):
    # 背景：地形
    centers = [(xi.nodes[i].x_km, xi.nodes[i].y_km) for i in xi.customers]
    g = np.linspace(-half, half, 161)
    Z = np.array([[terrain_height_m(x, y, centers, xi.xi) for x in g] for y in g])
    cf = ax.contourf(g, g, Z, levels=20, cmap="Greys", alpha=0.35)
    if Z.max() > 0:
        ax.contour(g, g, Z, levels=np.arange(50, Z.max() + 50, 50), colors="0.55", linewidths=0.4)
    # NCR の候補
    if prob.n_ncr:
        ax.scatter([p.x_km for p in prob.ncr_points], [p.y_km for p in prob.ncr_points], s=6, c="0.6",
                   marker=".", zorder=2)

    def xy(st):
        p = prob.point(0 if st.kind == "depot" else (st.ref if st.kind == "customer" else prob.ncr_loc(st.ref)))
        return p.x_km, p.y_km

    uid_xy = {st.uid: xy(st) for st in sol.stops}
    # トラックの経路
    pts = [uid_xy[st.uid] for st in sol.stops]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle="-|>", color="#1f4e9c", lw=1.6, mutation_scale=10), zorder=4)
    # ドローン
    for j, how in sol.drone.items():
        cj = prob.point(j)
        if isinstance(how, Loop):
            x0, y0 = uid_xy[how.at]
            ax.plot([x0, cj.x_km], [y0, cj.y_km], ls="--", c="#e67e22", lw=1.0, zorder=3)
        else:
            x0, y0 = uid_xy[how.launch]
            x1, y1 = uid_xy[how.retrieve]
            ax.plot([x0, cj.x_km, x1], [y0, cj.y_km, y1], ls="--", c="#c0392b", lw=1.0, zorder=3)
    # 客・デポ・使った NCR
    truck_c = {st.ref for st in sol.stops if st.kind == "customer"}
    for j in range(1, prob.n + 1):
        p = prob.point(j)
        heavy = not T.drone_ok[j]
        ax.scatter(p.x_km, p.y_km, s=42 if heavy else 30, marker="s" if heavy else "o",
                   c="#1f4e9c" if j in truck_c else "#e67e22", edgecolors="k", linewidths=0.5, zorder=5)
    used = [st for st in sol.stops if st.kind == "ncr"]
    ax.scatter([uid_xy[st.uid][0] for st in used], [uid_xy[st.uid][1] for st in used], s=90, marker="^",
               c="#2ca02c", edgecolors="k", linewidths=0.7, zorder=6)
    ax.scatter(0, 0, s=180, marker="*", c="gold", edgecolors="k", linewidths=0.8, zorder=7)
    n_sor = sum(1 for h in sol.drone.values() if isinstance(h, Sortie))
    n_loop = sum(1 for h in sol.drone.values() if isinstance(h, Loop))
    ax.set_title(f"{title}\n総 {ev.energy_kwh:.2f} kWh（トラック {ev.truck_kwh:.2f}，ドローン {ev.drone_kwh:.2f}）\n"
                 f"トラックの客 {len(truck_c)}，NCR の停車 {len(used)}，出撃 {n_sor}，往復 {n_loop}，"
                 f"完了 {ev.completion_h * 60:.0f} 分，待ち {ev.wait_h * 60:.0f} 分", fontsize=9)
    ax.set_xlim(-half, half)
    ax.set_ylim(-half, half)
    ax.set_aspect("equal")
    ax.set_xlabel("x [km]")
    ax.set_ylabel("y [km]")
    return cf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--titles", nargs="+", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    xi = xiao_instance(a.instance)
    half = (xi.grid_half_width_km / 2.0 if xi.coord_mode == "side" else xi.grid_half_width_km) * xi.coord_scale
    titles = a.titles or [Path(r).name for r in a.runs]
    k = len(a.runs)
    fig = plt.figure(figsize=(7.2 * k, 10.5))
    gs = fig.add_gridspec(2, k, height_ratios=[3.2, 1.0], hspace=0.28, wspace=0.18)
    ax_h = fig.add_subplot(gs[1, :])
    cf = None
    for c, (run, title) in enumerate(zip(a.runs, titles)):
        sol, ncr, hist = load_run(run)
        has_drone = bool(sol.drone)
        prob = from_xiao(xi, ncr)
        T = build_tables(prob)
        T.Q_t = 1e12   # 積載の上限は描画では見ない
        opts = Options(drones_enabled=has_drone, max_visits=None)
        ev = evaluate(prob, T, sol, opts)
        if not ev.feasible:
            print(f"warning: {run}: {ev.errors[:3]}")
        ax = fig.add_subplot(gs[0, c])
        cf = draw_map(ax, prob, T, sol, ev, xi, title, half)
        if hist:
            ax_h.plot([int(h["it"]) for h in hist], [float(h["best_kwh"]) for h in hist], label=title)
    ax_h.set_xlabel("反復")
    ax_h.set_ylabel("最良の総エネルギー [kWh]")
    ax_h.grid(alpha=0.3)
    ax_h.legend(fontsize=9)
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
    fig.legend(handles=handles, loc="upper center", ncol=9, fontsize=8.5, frameon=False, bbox_to_anchor=(0.5, 0.995))
    fig.suptitle(f"{a.instance}（客 {xi.n_customers} 人，ξ = {xi.xi:.0f}，背景は標高・等高線 50 m）", y=0.965, fontsize=12)
    fig.savefig(a.out, dpi=130, bbox_inches="tight")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
