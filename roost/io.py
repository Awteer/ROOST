"""解の保存と読み込み（JSON）．run_alns.py・batch_e1.py・plot_solutions.py で共通に使う．

形式：
{
  "stops": [{"uid": 0, "kind": "depot", "ref": 0}, ...],
  "drone": {"5": {"type": "loop", "at": 3}, "7": {"type": "sortie", "launch": 0, "retrieve": 4}},
  "ncr_points": [{"ell": 0, "x_km": ..., "y_km": ..., "z_m": ...}, ...]
}
"""

from __future__ import annotations

import json
from pathlib import Path

from .problem import Point, Problem
from .solution import Loop, Solution, Sortie, Stop


def solution_to_dict(prob: Problem, sol: Solution) -> dict:
    stops = [dict(uid=st.uid, kind=st.kind, ref=st.ref) for st in sol.stops]
    drone = {}
    for j, how in sorted(sol.drone.items()):
        drone[str(j)] = dict(type="loop", at=how.at) if isinstance(how, Loop) else \
            dict(type="sortie", launch=how.launch, retrieve=how.retrieve)
    return dict(stops=stops, drone=drone,
                ncr_points=[dict(ell=ell, x_km=p.x_km, y_km=p.y_km, z_m=p.z_m) for ell, p in enumerate(prob.ncr_points)])


def solution_from_dict(d: dict) -> tuple[Solution, tuple[Point, ...]]:
    stops = [Stop(uid=s["uid"], kind=s["kind"], ref=s["ref"]) for s in d["stops"]]
    drone = {}
    for j, h in d["drone"].items():
        drone[int(j)] = Loop(h["at"]) if h["type"] == "loop" else Sortie(h["launch"], h["retrieve"])
    ncr = tuple(Point(p["x_km"], p["y_km"], p["z_m"]) for p in d.get("ncr_points", []))
    return Solution(stops=stops, drone=drone), ncr


def save_solution(path: str | Path, prob: Problem, sol: Solution) -> None:
    Path(path).write_text(json.dumps(solution_to_dict(prob, sol), indent=1), encoding="utf-8")


def load_solution(path: str | Path) -> tuple[Solution, tuple[Point, ...]]:
    return solution_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
