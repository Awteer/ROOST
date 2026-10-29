# ROOST

NCR（客でない合流点）を含むトラック－ドローン協調配送を解く簡易 ALNS．
目的は総エネルギー最小，完了時刻の上限 $T_{\max}$ つき．停車での往復（同じ点で発射・回収）と出撃（別の点で発射・回収）の両方を扱う．

- 経緯・決まった設計・未決の点：[`docs/HANDOFF_20261026.md`](docs/HANDOFF_20261026.md)
- エネルギーの式とインスタンスの生成は，Xiao (2024) の再現実装（別リポジトリ Awteer/XIAO，PC では `C:\Research\code\XIAO`）から借りる

## 状態

ALNS まで（2026-10-29）．設計は [`docs/DESIGN_20261029.md`](docs/DESIGN_20261029.md)．

| ファイル | 中身 |
|---|---|
| `roost/problem.py` | 問題データ（デポ・客・NCR の候補地点）と設定 `Options` |
| `roost/tables.py` | 前もって計算する表（トラックのエネルギーの区分線形，ドローンの往路・復路） |
| `roost/solution.py` | 解の表し方 A（停車の列＋ドローン客ごとの配り方） |
| `roost/evaluate.py` | 形のチェックと評価器 v1 |
| `roost/moves.py` | 客の抜き方，NCR の停車のまとめ方・消し方，客 1 人の入れ方の候補（T・O・S・NO・NSL・NSR） |
| `roost/operators.py` | 壊す 5 つ（random，cluster，ncr_open，ncr_close，ncr_move），直す 4 つ（greedy_tfss，nearby_tfss，closest，heavy） |
| `roost/initial.py` | 初期解（Sacramento：最近傍 → 文字列の付け替え → ドローンの追加） |
| `roost/alns.py` | ALNS の本体（SA，重みの適応，改善なしで最良解に戻る，T_max の罰金 λ の調整） |
| `roost/milp_io.py` | NCR_MILP の結果（CSV）を ROOST の解に直す |
| `tools/verify_milp.py` | 評価器の照合（MILP の最適解を評価器にかけて値を比べる） |
| `tools/compare_milp.py` | 探索の確認（MILP の最適値が分かっている 346 本を ALNS で解いて差を見る） |
| `tools/run_alns.py` | Xiao 型のインスタンスを解いて結果フォルダに書く |
| `run/*.bat` | PC で実行する用（テスト，探索の確認，ALNS の実行） |
| `tests/` | 表と energy.py の一致，MILP の最適解の再現，違反の検出，オペレータ，ALNS |

## 使い方

XIAO は隣のフォルダ（`C:\Research\code\XIAO`）を読む．別の場所なら環境変数 `XIAO_PATH` で指定する．

```
python -m pytest tests
python tools/verify_milp.py --results ..\NCR_MILP\results --out results\verify_milp.csv
python tools/compare_milp.py --results ..\NCR_MILP\results --iterations 2000 --seeds 1 2 3 --out results\compare_milp.csv
python tools/run_alns.py --instance 20.20.1.a --modes 2 3 4 5 --ncr-grid 7 --iterations 5000 --seeds 1 2 3 --name n20-grid7
```

PC では `run\10_test.bat`，`run\20_compare_milp.bat`，`run\30_run_alns.bat`（中の設定を書き換えて使う）．

### 制約（今の版）

* トラックは 1 台．需要の合計がトラックの積載上限（300 kg）を超えるインスタンスは解けない
  （Xiao の生成器では客 20 人で 187 kg，30 人で 418 kg，50 人で 401 kg．`--capacity-kg` で上限を変えられるが Xiao のモデルとは別物）
* 評価器は v1（丸ごと評価）．客 50 人・NCR の候補 48 点で 1 反復 約 0.12 秒（クラウドの計測）

## 評価器の照合（2026-10-29）

NCR_MILP の最適解 346 本（価値の地図 300，T_max 掃引 46）を ROOST の評価器にかけ，全部一致した．
総エネルギーの相対誤差の最大は MILP の目的の値に対して 7.0e-11，独立の検算器 check.py に対して 1.7e-12．
完了時刻の差の最大は 9.0e-11 分，待ちの差の最大は 2.0e-10 分．

## 探索の確認（2026-10-29．各 1 本・seed 1・2000 反復，クラウドで計測）

MILP の最適値が分かっている 346 本を ALNS で解いた（`tools/compare_milp.py`）．1 本 2.5 秒前後．

| 対象 | 本数 | 最適値に届いた（差 < 0.01%） | 差 0.5% 以内 | 差の最大 |
|---|---|---|---|---|
| 価値の地図（客 6 人，往復なし） | 150 | 150 | 150 | 0.00% |
| 価値の地図（客 8 人，往復なし） | 150 | 137 | 139 | 5.28% |
| T_max 掃引（8.20.9.a，5 条件） | 46 | 42 | 44 | 1.16% |

MILP の最適値より良い解は 0 本（評価の食い違いはない）．届かなかったのは往復なしの条件（出撃だけ）に集中している．
seed を増やす・反復を増やすと届く例が多い（客 8 人の難しい 5 例で 4000 反復・seed 3 本なら 15 本中 13 本が最適値）．
