"""E2 の解の図の束を作る（仮説づくり用．2026-11-07）．

束 A（--sheets A）：1 枚 ＝ 1 つの配置・電池・seed．行 ＝ 地形 4 種（flat，slope，undul，atami），
  列 ＝ (2)→(2)，(2)→(4)，(3)→(3)，(3)→(5)，(2)→(4) T_max 0.85×T_ref．
束 B（--sheets B）：1 枚 ＝ 1 つの舞台（配置・地形・電池）・seed．(2)→(2) と (2)→(4) を T_max の 8 水準で並べる．
束 C（--sheets C）：NCR の価値（→4 と →2 の差，→5 と →3 の差）の表を地形×電池×配置で色分けした図．

仮説を作るデータと確かめるデータを分けるため，既定では seed 1 と 2 だけを描く（seed 3 は検証用．見ない）．

使い方（ROOST フォルダで）
  python tools/plot_e2_sheets.py --out results/20261105_e2 --sheets A C
出力：results/20261105_e2/figs/ に PNG と，束ごとの PDF（E2_sheets_A_seed12.pdf など）．
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from roost.terrain import TerrainSpec, make_terrain  # noqa: E402
from batch_e2 import BATTERIES, LAYOUTS, TERRAINS, TMAX_RATIOS, stage_name  # noqa: E402

plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP", "IPAexGothic", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

TERRAIN_JA = {"flat": "平地", "slope": "傾きだけ", "undul": "起伏だけ", "atami": "熱海型"}
BATTERY_JA = {"b150": "電池1.5", "b030": "電池0.30"}
_terrain_cache: dict = {}


def terrain_of(st: dict):
    key = (st["terrain"], st["terrain_seed"], st["side_km"])
    if key not in _terrain_cache:
        _terrain_cache[key] = make_terrain(replace(TerrainSpec(side_km=st["side_km"], seed=st["terrain_seed"]),
                                                   **TERRAINS[st["terrain"]]))
    return _terrain_cache[key]


def load(out: Path, tag: str):
    rp = out / "raw" / f"{tag}_result.json"
    if not rp.exists():
        return None, None
    res = json.loads(rp.read_text(encoding="utf-8"))
    bp = out / "raw" / f"{tag}_best.json"
    sol = json.loads(bp.read_text(encoding="utf-8")) if bp.exists() else None
    return res, sol


def draw(ax, st: dict, res, sol, title: str, ref_kwh: float | None = None) -> None:
    half = st["side_km"] / 2
    ter = terrain_of(st)
    if ter.z.max() - ter.z.min() < 1.0:   # 平地は一面の薄い灰色（terrain の色だと海に見えるため）
        ax.imshow(np.zeros_like(ter.z), origin="lower", extent=[-half, half, -half, half], cmap="Greys",
                  vmin=-1, vmax=8)
    else:
        ax.imshow(ter.z, origin="lower", extent=[-half, half, -half, half], cmap="terrain", vmin=-60, vmax=650,
                  alpha=0.85, interpolation="bilinear")
    if ter.z.max() > ter.z.min() + 1:
        ax.contour(ter.xs, ter.ys, ter.z, levels=np.arange(0, 900, 50), colors="k", linewidths=0.25, alpha=0.6)
    ax.set_xlim(-half - 0.1, half + 0.1)
    ax.set_ylim(-half - 0.1, half + 0.1)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    dep, cs, ncr, ok = st["depot"], st["customers"], st["ncr_points"], st["drone_ok"]
    if res is None:
        ax.set_title(f"{title}\n（まだ結果なし）", fontsize=8)
        return
    if sol is None:
        msg = (f"T_max を守れる解なし（T_max {res['tmax_min']:.1f} 分）" if not res.get("feasible_found")
               else "解のファイルが見つからない")
        ax.set_title(f"{title}\n{msg}", fontsize=8, color="r")
        for k, c in enumerate(cs, start=1):
            ax.plot(c[0], c[1], "D" if not ok[k - 1] else "o", ms=5, mfc="r" if not ok[k - 1] else "w", mec="k")
        ax.plot(dep[0], dep[1], "s", ms=8, color="r", clip_on=False)
        return

    def pos(s):
        if s["kind"] == "depot":
            return dep[:2]
        if s["kind"] == "customer":
            return cs[s["ref"] - 1][:2]
        return ncr[s["ref"]][:2]

    uid = {s["uid"]: s for s in sol["stops"]}
    P = [pos(s) for s in sol["stops"]]
    ax.plot([p[0] for p in P], [p[1] for p in P], "-", color="#1f3a93", lw=1.8, zorder=3)
    for j, h in sol["drone"].items():
        c = cs[int(j) - 1][:2]
        if h["type"] == "loop":
            a = pos(uid[h["at"]])
            ax.plot([a[0], c[0]], [a[1], c[1]], "--", color="#d35400", lw=1.0, zorder=4)
        else:
            a, b = pos(uid[h["launch"]]), pos(uid[h["retrieve"]])
            ax.plot([a[0], c[0], b[0]], [a[1], c[1], b[1]], ":", color="#8e44ad", lw=1.3, zorder=4)
    tc = {s["ref"] for s in sol["stops"] if s["kind"] == "customer"}
    for k, c in enumerate(cs, start=1):
        if not ok[k - 1]:
            ax.plot(c[0], c[1], "D", ms=7, mfc="r", mec="k", zorder=6)
        elif k in tc:
            ax.plot(c[0], c[1], "o", ms=6, mfc="#1f3a93", mec="w", zorder=5)
        else:
            ax.plot(c[0], c[1], "o", ms=5, mfc="w", mec="#d35400", mew=1.3, zorder=5)
    for s in sol["stops"]:
        if s["kind"] == "ncr":
            p = ncr[s["ref"]]
            ax.plot(p[0], p[1], "^", ms=9, mfc="#f1c40f", mec="k", zorder=6)
    ax.plot(dep[0], dep[1], "s", ms=8, color="r", zorder=6, clip_on=False)
    diff = ""
    if ref_kwh:
        diff = f"（{(res['best_kwh'] - ref_kwh) / ref_kwh * 100:+.1f}%）"
    tm = f"／T_max {res['tmax_min']:.0f}分" if res.get("tmax_min") not in ("", None) else ""
    ax.set_title(f"{title}\n{res['best_kwh']:.2f} kWh{diff}  T {res['truck_kwh']:.2f}／D {res['drone_kwh']:.2f}\n"
                 f"寄る客{res['truck_customers']} NCR{res['ncr_stops']} 往復{res['loops']} 出撃{res['sorties']} "
                 f"完了{res['completion_min']:.0f}分{tm}", fontsize=7.5)


def legend_handles():
    return [Line2D([], [], color="#1f3a93", lw=2, label="トラック"),
            Line2D([], [], color="#d35400", ls="--", label="ドローン往復"),
            Line2D([], [], color="#8e44ad", ls=":", lw=1.5, label="ドローン出撃"),
            Line2D([], [], marker="s", color="r", ls="", ms=8, label="デポ（港）"),
            Line2D([], [], marker="^", mfc="#f1c40f", mec="k", ls="", ms=9, label="使われたNCR"),
            Line2D([], [], marker="o", mfc="#1f3a93", mec="w", ls="", ms=7, label="トラックが寄る客"),
            Line2D([], [], marker="o", mfc="w", mec="#d35400", ls="", ms=7, label="ドローンで配る客"),
            Line2D([], [], marker="D", mfc="r", mec="k", ls="", ms=7, label="重い客（必ずトラック）")]


def sheet_A(out: Path, lay: str, bat: str, seed: int):
    cols = [("m2_from-m2", "(2)→(2) NCRなし・往復なし", None),
            ("m4_from-m2", "(2)→(4) NCRあり・往復なし", "m2_from-m2"),
            ("m3_from-m3", "(3)→(3) NCRなし・往復あり", None),
            ("m5_from-m3", "(3)→(5) NCRあり・往復あり", "m3_from-m3"),
            ("m4_from-m2_T0850", "(2)→(4) T_max 0.85倍", "m2_from-m2_T0850")]
    fig, axs = plt.subplots(4, 5, figsize=(22, 21))
    for i, ter in enumerate(TERRAINS):
        stg = stage_name(lay, ter, bat)
        st = json.loads((out / "stages" / f"{stg}.json").read_text(encoding="utf-8"))
        for jcol, (suf, ttl, refsuf) in enumerate(cols):
            res, sol = load(out, f"{stg}_{suf}_s{seed}")
            ref = None
            if refsuf:
                r0, _ = load(out, f"{stg}_{refsuf}_s{seed}")
                ref = r0["best_kwh"] if r0 and r0.get("feasible_found") else None
            draw(axs[i, jcol], st, res, sol, f"{TERRAIN_JA[ter]}：{ttl}", ref)
    n, m = lay.split(".")
    fig.legend(handles=legend_handles(), loc="lower center", ncol=8, fontsize=11, frameon=False)
    fig.suptitle(f"E2 束A　客{n}人・配置{m}・{BATTERY_JA[bat]}・seed {seed}　（括弧の%は左の NCR なしとの差．1辺5 km，等高線50 m）",
                 fontsize=14)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97), h_pad=3.5)
    return fig


def sheet_B(out: Path, lay: str, ter: str, bat: str, seed: int):
    stg = stage_name(lay, ter, bat)
    st = json.loads((out / "stages" / f"{stg}.json").read_text(encoding="utf-8"))
    fig, axs = plt.subplots(2, len(TMAX_RATIOS), figsize=(4.4 * len(TMAX_RATIOS), 10.5))
    for k, r in enumerate(TMAX_RATIOS):
        code = f"T{int(round(r * 1000)):04d}"
        r2, s2 = load(out, f"{stg}_m2_from-m2_{code}_s{seed}")
        r4, s4 = load(out, f"{stg}_m4_from-m2_{code}_s{seed}")
        draw(axs[0, k], st, r2, s2, f"(2)→(2) T_max {r:g}倍")
        draw(axs[1, k], st, r4, s4, f"(2)→(4) T_max {r:g}倍",
             r2["best_kwh"] if r2 and r2.get("feasible_found") else None)
    n, m = lay.split(".")
    fig.legend(handles=legend_handles(), loc="lower center", ncol=8, fontsize=10, frameon=False)
    fig.suptitle(f"E2 束B　客{n}人・配置{m}・{TERRAIN_JA[ter]}・{BATTERY_JA[bat]}・seed {seed}　（T_max ＝ 倍率 × (2) の最良解の完了時刻）",
                 fontsize=13)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    return fig


def sheet_C(out: Path, seeds):
    """NCR の価値（%）：行 ＝ 配置×seed，列 ＝ 地形×電池．往復なし（→4 vs →2）と往復あり（→5 vs →3）．"""
    figs = []
    for name, a, b in (("往復なし：(2)→(4) と (2)→(2) の差 [%]", "m4_from-m2", "m2_from-m2"),
                       ("往復あり：(3)→(5) と (3)→(3) の差 [%]", "m5_from-m3", "m3_from-m3"),
                       ("往復なし・T_max 0.85倍：(2)→(4) と (2)→(2) の差 [%]（×：(2)が守れず (4)は守れた）",
                        "m4_from-m2_T0850", "m2_from-m2_T0850")):
        rows = [(lay, s) for lay in LAYOUTS for s in seeds]
        colsk = [(t, bt) for bt in BATTERIES for t in TERRAINS]
        M = np.full((len(rows), len(colsk)), np.nan)
        rescue = np.zeros_like(M, dtype=bool)
        for i, (lay, s) in enumerate(rows):
            for j, (t, bt) in enumerate(colsk):
                stg = stage_name(lay, t, bt)
                ra, _ = load(out, f"{stg}_{a}_s{s}")
                rb, _ = load(out, f"{stg}_{b}_s{s}")
                if ra and rb and ra.get("feasible_found") and rb.get("feasible_found"):
                    M[i, j] = (ra["best_kwh"] - rb["best_kwh"]) / rb["best_kwh"] * 100
                elif ra and rb and ra.get("feasible_found") and not rb.get("feasible_found"):
                    rescue[i, j] = True
        fig, ax = plt.subplots(figsize=(12, 0.42 * len(rows) + 2.5))
        im = ax.imshow(M, cmap="RdBu", vmin=-15, vmax=15, aspect="auto")
        for i in range(len(rows)):
            for j in range(len(colsk)):
                if not np.isnan(M[i, j]):
                    ax.text(j, i, f"{M[i, j]:+.1f}", ha="center", va="center", fontsize=8)
                elif rescue[i, j]:
                    ax.text(j, i, "×", ha="center", va="center", fontsize=10, color="k")
        ax.set_xticks(range(len(colsk)))
        ax.set_xticklabels([f"{TERRAIN_JA[t]}\n{BATTERY_JA[bt]}" for t, bt in colsk], fontsize=9)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([f"客{l.split('.')[0]} 配置{l.split('.')[1]} seed{s}" for l, s in rows], fontsize=8)
        ax.axvline(len(TERRAINS) - 0.5, color="k", lw=1.5)
        fig.colorbar(im, ax=ax, shrink=0.6, label="%（負＝NCRで減った）")
        ax.set_title(f"E2 束C　{name}　（空白：比べられない）", fontsize=11)
        fig.tight_layout()
        figs.append(fig)
    return figs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/20261105_e2")
    ap.add_argument("--sheets", nargs="+", default=["A", "C"], choices=["A", "B", "C"])
    ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2])
    ap.add_argument("--layouts", nargs="+", default=list(LAYOUTS))
    ap.add_argument("--dpi", type=int, default=70)
    a = ap.parse_args()
    out = Path(a.out)
    figdir = out / "figs"
    figdir.mkdir(parents=True, exist_ok=True)
    stag = "seed" + "".join(map(str, a.seeds))
    if "C" in a.sheets:
        with PdfPages(figdir / f"E2_sheets_C_{stag}.pdf") as pdf:
            for k, fig in enumerate(sheet_C(out, a.seeds)):
                fig.savefig(figdir / f"C_{k + 1}_{stag}.png", dpi=110)
                pdf.savefig(fig, dpi=110)
                plt.close(fig)
        print("C done", flush=True)
    if "A" in a.sheets:
        (figdir / "A").mkdir(exist_ok=True)
        with PdfPages(figdir / f"E2_sheets_A_{stag}.pdf") as pdf:
            for bat in BATTERIES:
                for lay in a.layouts:
                    for s in a.seeds:
                        fig = sheet_A(out, lay, bat, s)
                        fig.savefig(figdir / "A" / f"A_{stage_name(lay, 'all', bat)}_s{s}.png", dpi=a.dpi)
                        pdf.savefig(fig, dpi=a.dpi)
                        plt.close(fig)
                        print("A", lay, bat, s, flush=True)
    if "B" in a.sheets:
        (figdir / "B").mkdir(exist_ok=True)
        with PdfPages(figdir / f"E2_sheets_B_{stag}.pdf") as pdf:
            for bat in BATTERIES:
                for lay in a.layouts:
                    for ter in TERRAINS:
                        for s in a.seeds:
                            fig = sheet_B(out, lay, ter, bat, s)
                            fig.savefig(figdir / "B" / f"B_{stage_name(lay, ter, bat)}_s{s}.png", dpi=a.dpi)
                            pdf.savefig(fig, dpi=a.dpi)
                            plt.close(fig)
                            print("B", lay, ter, bat, s, flush=True)
    print("FINISHED", flush=True)


if __name__ == "__main__":
    main()
