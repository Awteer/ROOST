# ROOST

NCR（客でない合流点）を含むトラック－ドローン協調配送を解く簡易 ALNS．
目的は総エネルギー最小，完了時刻の上限 $T_{\max}$ つき．停車での往復（同じ点で発射・回収）と出撃（別の点で発射・回収）の両方を扱う．

- 経緯・決まった設計・未決の点：[`docs/HANDOFF_20261026.md`](docs/HANDOFF_20261026.md)
- エネルギーの式とインスタンスの生成は，Xiao (2024) の再現実装（別リポジトリ Awteer/XIAO，PC では `C:\Research\code\XIAO`）から借りる

## 状態

評価器 v1 まで（2026-10-29）．探索（ALNS のオペレータ）はまだない．

| ファイル | 中身 |
|---|---|
| `roost/problem.py` | 問題データ（デポ・客・NCR の候補地点）と設定 `Options` |
| `roost/tables.py` | 前もって計算する表（トラックのエネルギーの区分線形，ドローンの往路・復路） |
| `roost/solution.py` | 解の表し方 A（停車の列＋ドローン客ごとの配り方） |
| `roost/evaluate.py` | 形のチェックと評価器 v1 |
| `roost/milp_io.py` | NCR_MILP の結果（CSV）を ROOST の解に直す |
| `tools/verify_milp.py` | 評価器の照合（MILP の最適解を評価器にかけて値を比べる） |
| `tests/` | 表と energy.py の一致，MILP の最適解の再現，違反の検出 |

- オペレータの設計：[`docs/DESIGN_20261029.md`](docs/DESIGN_20261029.md)

## 使い方

XIAO は隣のフォルダ（`C:\Research\code\XIAO`）を読む．別の場所なら環境変数 `XIAO_PATH` で指定する．

```
python -m pytest tests
python tools/verify_milp.py --results ..\NCR_MILP\results --out results\verify_milp.csv
```

## 評価器の照合（2026-10-29）

NCR_MILP の最適解 346 本（価値の地図 300，T_max 掃引 46）を ROOST の評価器にかけ，全部一致した．
総エネルギーの相対誤差の最大は MILP の目的の値に対して 7.0e-11，独立の検算器 check.py に対して 1.7e-12．
完了時刻の差の最大は 9.0e-11 分，待ちの差の最大は 2.0e-10 分．
