"""发布包元数据回归测试。"""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from bsa import __version__


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    """防止修改安装包后仍沿用旧版本号。"""

    def test_release_version_and_chinese_product_name(self) -> None:
        manifest = tomllib.loads(
            (REPOSITORY_ROOT / "blender_manifest.toml").read_text(encoding="utf-8")
        )
        project = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["version"], "0.9.0")
        self.assertEqual(project["project"]["version"], manifest["version"])
        self.assertEqual(__version__, manifest["version"])
        self.assertEqual(manifest["name"], "3D 打印零件助手")
        self.assertIn("network", manifest["permissions"])
        self.assertIn("用户自行配置", manifest["permissions"]["network"])


if __name__ == "__main__":
    unittest.main()
