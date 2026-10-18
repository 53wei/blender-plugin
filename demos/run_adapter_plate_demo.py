"""输出一个不依赖 Blender 或网络的矩形转接板 P0 演示。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from bsa.core.adapter_plate import design_adapter_plate, resize_adapter_plate  # noqa: E402
from bsa.domain.adapter_plate import (  # noqa: E402
    AdapterPlateResizePatch,
    AdapterPlateSpec,
    MountingPatternSpec,
    PatternHoleSpec,
)


def main() -> int:
    spec = AdapterPlateSpec(
        plate_id="adapter-demo",
        width_mm=80.0,
        depth_mm=40.0,
        thickness_mm=3.0,
        corner_radius_mm=2.0,
        mounting_patterns=(
            MountingPatternSpec(
                "device",
                20.0,
                20.0,
                (
                    PatternHoleSpec("device-left", -10.0, 0.0, 3.2),
                    PatternHoleSpec("device-right", 10.0, 0.0, 3.2),
                ),
            ),
            MountingPatternSpec(
                "support",
                40.0,
                20.0,
                (
                    PatternHoleSpec("support-front", 0.0, -10.0, 4.2),
                    PatternHoleSpec("support-back", 0.0, 10.0, 4.2),
                ),
            ),
        ),
    )
    before = design_adapter_plate(spec)
    revision = resize_adapter_plate(
        spec,
        AdapterPlateResizePatch(
            new_width_mm=90.0,
            new_depth_mm=None,
            fixed_x_edge="left",
            fixed_y_edge="front",
            preserve_pattern_ids=("device", "support"),
        ),
    )
    print("修改前：")
    print(json.dumps(before.to_dict(), ensure_ascii=False, indent=2))
    print("\n从左边加长 10 mm 后（孔位保持不变）：")
    print(json.dumps(revision.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
