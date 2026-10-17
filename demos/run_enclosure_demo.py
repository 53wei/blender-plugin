"""输出合成电路板外壳的 P0 设计与打印检查结果。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from bsa.core.enclosure import design_enclosure, inspect_enclosure_design  # noqa: E402
from bsa.domain.enclosure import (  # noqa: E402
    BoardSpec,
    EnclosureParameters,
    FdmPrintProfile,
    MountingHoleSpec,
    RectangularPortSpec,
)


def main() -> int:
    board = BoardSpec(
        board_id="synthetic-demo-board",
        width_mm=70.0,
        depth_mm=50.0,
        height_mm=12.0,
        mounting_holes=(
            MountingHoleSpec("h1", 5.0, 5.0, 3.2),
            MountingHoleSpec("h2", 65.0, 5.0, 3.2),
            MountingHoleSpec("h3", 65.0, 45.0, 3.2),
            MountingHoleSpec("h4", 5.0, 45.0, 3.2),
        ),
        ports=(RectangularPortSpec("usb", "front", 35.0, 1.0, 12.0, 6.0),),
    )
    parameters = EnclosureParameters(
        wall_thickness_mm=2.0,
        floor_thickness_mm=2.0,
        lid_thickness_mm=2.0,
        board_clearance_xy_mm=1.0,
        top_clearance_mm=3.0,
        boss_height_mm=4.0,
        boss_outer_diameter_mm=6.0,
        screw_hole_diameter_mm=2.6,
        port_clearance_mm=0.5,
        corner_radius_mm=2.0,
    )
    profile = FdmPrintProfile(
        profile_id="synthetic-fdm",
        nozzle_diameter_mm=0.4,
        minimum_wall_thickness_mm=1.2,
        minimum_hole_diameter_mm=2.0,
        minimum_fit_clearance_mm=0.25,
    )
    design = design_enclosure(board, parameters)
    payload = {
        "fixture_kind": "synthetic_not_physically_validated",
        "design": design.to_dict(),
        "print_issues": [
            issue.to_dict() for issue in inspect_enclosure_design(design, profile)
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
