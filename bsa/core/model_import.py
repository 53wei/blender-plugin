"""Validation for model files accepted by the guided import step."""

from __future__ import annotations

from pathlib import Path

from ..domain.errors import DomainError, ErrorCode

SUPPORTED_MODEL_FORMATS = {
    ".blend": "Blender",
    ".fbx": "FBX",
    ".glb": "glTF Binary",
    ".gltf": "glTF",
    ".obj": "Wavefront OBJ",
    ".ply": "Stanford PLY",
    ".stl": "STL",
}

MODEL_FILE_FILTER = "*.blend;*.fbx;*.glb;*.gltf;*.obj;*.ply;*.stl"


def model_format(path: str | Path) -> str:
    """Return the normalized model suffix or fail with a user-safe error."""

    suffix = Path(path).suffix.lower()
    if suffix not in SUPPORTED_MODEL_FORMATS:
        raise DomainError(
            ErrorCode.ACTION_NOT_SUPPORTED,
            "Unsupported model file format",
            {"suffix": suffix or "<none>"},
        )
    return suffix


def validate_model_paths(
    paths: tuple[str | Path, ...],
    *,
    require_exists: bool = False,
) -> tuple[Path, ...]:
    """Validate, de-duplicate, and normalize an import batch."""

    normalized: list[Path] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        model_format(path)
        key = str(path.absolute()).casefold()
        if key in seen:
            continue
        if require_exists and not path.is_file():
            raise DomainError(
                ErrorCode.PRECONDITION_FAILED,
                "Model file does not exist",
                {"path": str(path)},
            )
        seen.add(key)
        normalized.append(path)
    if not normalized:
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED,
            "Select at least one supported model file",
        )
    return tuple(normalized)
