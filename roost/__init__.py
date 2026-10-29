"""ROOST：NCR（客でない合流点）を含むトラック－ドローン協調配送の簡易 ALNS．

いまあるもの（2026-10-29）
--------------------------
* problem.py  ：問題データ（デポ・客・NCR の候補地点）と設定（Options）
* tables.py   ：前もって計算する表（距離・時間・トラックのエネルギーの区分線形・ドローンの往路と復路）
* solution.py ：解の表し方 A（停車の列＋ドローン客ごとの配り方）
* evaluate.py ：形のチェックと評価器 v1（列を前から 1 回なめて，毎回全部を評価し直す）
* milp_io.py  ：NCR_MILP の結果（CSV の route・sorties・loops）を ROOST の解に直す

設計の経緯は docs/HANDOFF_20261026.md と docs/DESIGN_20261029.md．
エネルギーの式は XIAO（xiao/energy.py）の関数をそのまま使う．
"""

# --- XIAO を import できるようにする ---
# XIAO の場所は環境変数 XIAO_PATH があればそこ．なければ ROOST と同じ階層の XIAO フォルダ
# （PC では C:\Research\code\XIAO）．小文字の xiao フォルダでもよい．NCR_MILP・CITY と同じ約束．
import os as _os
import sys as _sys
from pathlib import Path as _Path


def _find_xiao() -> _Path:
    env = _os.environ.get("XIAO_PATH")
    if env:
        return _Path(env).resolve()
    parent = _Path(__file__).resolve().parents[2]
    for name in ("XIAO", "xiao"):
        cand = parent / name
        if (cand / "xiao").is_dir():
            return cand.resolve()
    return (parent / "XIAO").resolve()


_XIAO = _find_xiao()
if not (_XIAO / "xiao").is_dir():
    raise ImportError(f"XIAO が見つからない：{_XIAO}（環境変数 XIAO_PATH で場所を指定できる）")
if str(_XIAO) not in _sys.path:
    _sys.path.insert(0, str(_XIAO))
XIAO_PATH = _XIAO

from .evaluate import Evaluation, evaluate  # noqa: E402
from .problem import Options, Point, Problem  # noqa: E402
from .solution import Loop, Solution, Sortie, Stop  # noqa: E402
from .tables import Tables, build_tables  # noqa: E402

__all__ = [
    "Evaluation", "Loop", "Options", "Point", "Problem", "Solution", "Sortie", "Stop", "Tables",
    "XIAO_PATH", "build_tables", "evaluate",
]
