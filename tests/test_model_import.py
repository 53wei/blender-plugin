"""Model import validation stays testable without Blender."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bsa.core.model_import import (
    MODEL_FILE_FILTER,
    SUPPORTED_MODEL_FORMATS,
    model_format,
    validate_model_paths,
)
from bsa.domain.errors import DomainError, ErrorCode


class ModelImportTests(unittest.TestCase):
    def test_expected_existing_model_formats_are_supported(self) -> None:
        self.assertEqual(
            set(SUPPORTED_MODEL_FORMATS),
            {".blend", ".fbx", ".glb", ".gltf", ".obj", ".ply", ".stl"},
        )

    def test_extensions_are_case_insensitive(self) -> None:
        self.assertEqual(model_format("Chair.FBX"), ".fbx")

    def test_file_filter_lists_every_supported_suffix(self) -> None:
        for suffix in SUPPORTED_MODEL_FORMATS:
            self.assertIn(f"*{suffix}", MODEL_FILE_FILTER)

    def test_duplicate_paths_are_removed_without_reordering(self) -> None:
        paths = validate_model_paths(("chair.obj", "desk.glb", "chair.obj"))
        self.assertEqual(tuple(path.name for path in paths), ("chair.obj", "desk.glb"))

    def test_missing_and_unsupported_files_fail_with_stable_errors(self) -> None:
        with self.assertRaises(DomainError) as unsupported:
            validate_model_paths(("readme.txt",))
        self.assertEqual(unsupported.exception.code, ErrorCode.ACTION_NOT_SUPPORTED)
        with tempfile.TemporaryDirectory() as directory:
            missing_path = Path(directory) / "missing.obj"
            with self.assertRaises(DomainError) as missing:
                validate_model_paths((missing_path,), require_exists=True)
        self.assertEqual(missing.exception.code, ErrorCode.PRECONDITION_FAILED)


if __name__ == "__main__":
    unittest.main()
