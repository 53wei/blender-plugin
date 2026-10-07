"""Run and record the first complete deterministic product slice."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from bsa.application.service import SceneEditingService  # noqa: E402
from tests.support import make_place_plan, make_scene  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "benchmarks" / "results" / "m1_results.json",
    )
    args = parser.parse_args()

    scene = make_scene()
    plan = make_place_plan(scene, region="right", lock_target=True)
    started = time.perf_counter()
    result = SceneEditingService(scene).execute_plan(plan)
    duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
    final_objects = scene.read_snapshot().object_map()
    report = {
        "case_id": "m1-demo-001",
        "instruction": "Place Lamp on the right side of Desk and protect Desk",
        "duration_ms": duration_ms,
        "result": result.to_dict(),
        "final_state": {
            "lamp_location": final_objects["lamp-id"].location_world,
            "desk_locked": final_objects["desk-id"].locked,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.status == "COMMITTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
