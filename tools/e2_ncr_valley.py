"""E2：NCR 候補の「谷らしさ」D_h(r) と，解での使われ方の関係（2026-11-08）．

使い方（ROOST フォルダで．先に tools/e2_tables.py を同じ --seeds で実行しておく）
  python tools/e2_ncr_valley.py --out results/20261105_e2 --seeds 1 2
出力：results/20261105_e2/analysis_s12/ に E2_ncr_valley_s12.csv（相関），E2_ncr_candidates_s12.csv（候補ごと），
      E2_ncr_valley_s12.png（地図）


D_h(r) = z(r) - (半径 h の円周上の z の平均)．傾いた平面では 0．負＝谷・窪み，正＝尾根．
使われ方：T_max なしの (2)→(4)，(3)→(5) の解（配置 10 × seed の数）で，候補 r が NCR として使われた割合．
地形の効果だけを見るため，同じ候補・同じ配置の平地での使われ方を引いた差も見る（起伏だけ − 平地，熱海型 − 傾きだけ）．
"""
import argparse
import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from roost import terrain as T  # noqa: E402
from batch_e2 import SIDE_KM, TERRAIN_SEED, TERRAINS  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="results/20261105_e2")
ap.add_argument("--seeds", nargs="+", type=int, default=[1, 2])
args = ap.parse_args()
SEEDS = tuple(args.seeds)
TAG = "s" + "".join(map(str, SEEDS))
SRC = Path(args.out)
OUT = SRC / f"analysis_{TAG}"
OUT.mkdir(parents=True, exist_ok=True)
HS = (0.25, 0.5, 1.0)

ter = {k: T.make_terrain(replace(T.TerrainSpec(side_km=SIDE_KM, seed=TERRAIN_SEED), **v)) for k, v in TERRAINS.items()}
st0 = json.loads((SRC / "stages" / "n20m1_atami_b030.json").read_text(encoding="utf-8"))
P = np.array(st0["ncr_points"])[:, :2]
th = np.linspace(0, 2 * np.pi, 64, endpoint=False)


def D(t, h):
    out = []
    for x, y in P:
        xs, ys = x + h * np.cos(th), y + h * np.sin(th)
        inside = (np.abs(xs) <= 2.5) & (np.abs(ys) <= 2.5)   # 領域の外の点は使わない（端では半分欠ける）
        out.append(t.height(x, y) - t.height(xs[inside], ys[inside]).mean())
    return np.array(out)


Dv = {(k, h): D(ter[k], h) for k in ter for h in HS}

# 使われ方
use = {}
for ter_name in TERRAINS:
    for bat in ("b150", "b030"):
        for mode, tagp in (("noloop", "m4_from-m2"), ("loop", "m5_from-m3")):
            cnt = np.zeros(len(P)); nsol = 0
            for n in (20, 25):
                for m in range(1, 6):
                    for s in SEEDS:
                        r = json.loads((SRC / "raw" / f"n{n}m{m}_{ter_name}_{bat}_{tagp}_s{s}_result.json").read_text(encoding="utf-8"))
                        for ref in r["ncr_refs"]:
                            cnt[ref] += 1
                        nsol += 1
            use[(ter_name, bat, mode)] = cnt / nsol


def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    return np.corrcoef(ra, rb)[0, 1]


def perm_p(a, b, k=5000, seed=0):
    rng = np.random.default_rng(seed); r0 = spearman(a, b)
    rs = np.array([spearman(a, rng.permutation(b)) for _ in range(k)])
    return float((np.abs(rs) >= abs(r0)).mean())


rows = []
print("terrain base bat mode h | rho(D,use) p | rho(D,use-base) p | D_mean(all) D_mean(use-weighted)")
for ter_name, base in (("undul", "flat"), ("atami", "slope")):
    for bat in ("b150", "b030"):
        for mode in ("noloop", "loop"):
            u = use[(ter_name, bat, mode)]; du = u - use[(base, bat, mode)]
            for h in HS:
                d = Dv[(ter_name, h)]
                r1, r2 = spearman(d, u), spearman(d, du)
                p1, p2 = perm_p(d, u), perm_p(d, du)
                wmean = float((d * u).sum() / u.sum())
                rows.append(dict(terrain=ter_name, base=base, battery=bat, mode=mode, h_km=h, rho_use=r1, p_use=p1,
                                 rho_diff=r2, p_diff=p2, D_mean_all=d.mean(), D_mean_used=wmean))
                print(ter_name, base, bat, mode, h, "| %.2f %.3f | %.2f %.3f | %.1f %.1f" % (r1, p1, r2, p2, d.mean(), wmean))

with open(OUT / f"E2_ncr_valley_{TAG}.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

# 候補ごとの表
with open(OUT / f"E2_ncr_candidates_{TAG}.csv", "w", newline="", encoding="utf-8-sig") as f:
    keys = ["ref", "x_km", "y_km", "z_undul", "z_atami"] + [f"D{h}_{k}" for k in ("undul", "atami") for h in HS] + \
           [f"use_{k}_{b}_{m}" for k in TERRAINS for b in ("b150", "b030") for m in ("noloop", "loop")]
    w = csv.writer(f); w.writerow(keys)
    for i, (x, y) in enumerate(P):
        w.writerow([i, x, y, float(ter["undul"].height(x, y)), float(ter["atami"].height(x, y))]
                   + [round(float(Dv[(k, h)][i]), 2) for k in ("undul", "atami") for h in HS]
                   + [round(float(use[(k, b, m)][i]), 3) for k in TERRAINS for b in ("b150", "b030") for m in ("noloop", "loop")])

# 図：h=0.5 の D の地図と，起伏だけ・電池0.30・往復なし の使われ方（平地との差）
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP", "sans-serif"]
fig, axs = plt.subplots(2, 3, figsize=(16, 10.5))
for row, (tn, base) in enumerate((("undul", "flat"), ("atami", "slope"))):
    t = ter[tn]
    ax = axs[row, 0]
    im = ax.imshow(t.z, origin="lower", extent=[-2.5, 2.5, -2.5, 2.5], cmap="terrain")
    sc = ax.scatter(P[:, 0], P[:, 1], c=Dv[(tn, 0.5)], cmap="coolwarm_r", vmin=-60, vmax=60, s=40, edgecolor="k")
    plt.colorbar(sc, ax=ax, label="D_0.5 [m]（負＝谷）")
    ax.set_title(f"{'起伏だけ' if tn=='undul' else '熱海型'}：候補の谷らしさ D（h=0.5 km）")
    for col, bat in ((1, "b150"), (2, "b030")):
        ax = axs[row, col]
        ax.imshow(t.z, origin="lower", extent=[-2.5, 2.5, -2.5, 2.5], cmap="terrain", alpha=0.6)
        du = use[(tn, bat, "noloop")] - use[(base, bat, "noloop")]
        sc = ax.scatter(P[:, 0], P[:, 1], c=du, cmap="PuOr", vmin=-0.5, vmax=0.5, s=40 + 300 * use[(tn, bat, "noloop")], edgecolor="k")
        plt.colorbar(sc, ax=ax, label=f"使われた割合の差（{tn}−{base}）")
        ax.set_title(f"{'電池1.5' if bat=='b150' else '電池0.30'} 往復なし：大きさ＝使われた割合，色＝{base}との差")
for ax in axs.flat:
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
fig.suptitle(f"NCR 候補の谷らしさと使われ方（seed {SEEDS}，T_max なし，{10 * len(SEEDS)} 解ずつ）")
fig.tight_layout()
fig.savefig(OUT / f"E2_ncr_valley_{TAG}.png", dpi=110)
