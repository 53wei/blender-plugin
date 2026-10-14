"""Transactional Blender import adapter for existing model assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import bpy

from ..core.model_import import model_format, validate_model_paths
from ..domain.errors import DomainError, ErrorCode
from .ids import ensure_stable_ids


@dataclass(frozen=True)
class ImportBatchResult:
    """Names and counts safe to display after a completed import."""

    files: tuple[str, ...]
    object_names: tuple[str, ...]


def _append_blend_objects(context: object, filepath: Path) -> None:
    with bpy.data.libraries.load(str(filepath), link=False) as (data_from, data_to):
        data_to.objects = tuple(data_from.objects)
    for obj in data_to.objects:
        if obj is not None and obj.name not in context.scene.objects:
            context.collection.objects.link(obj)


def _run_import(context: object, filepath: Path) -> None:
    suffix = model_format(filepath)
    if suffix == ".blend":
        _append_blend_objects(context, filepath)
        return
    elif suffix == ".fbx":
        status = bpy.ops.import_scene.fbx(filepath=str(filepath))
    elif suffix in {".glb", ".gltf"}:
        status = bpy.ops.import_scene.gltf(filepath=str(filepath))
    elif suffix == ".obj":
        status = bpy.ops.wm.obj_import(filepath=str(filepath))
    elif suffix == ".ply":
        status = bpy.ops.wm.ply_import(filepath=str(filepath))
    elif suffix == ".stl":
        status = bpy.ops.wm.stl_import(filepath=str(filepath))
    else:  # The pure validator should make this unreachable.
        raise DomainError(ErrorCode.ACTION_NOT_SUPPORTED, "Unsupported import operator")
    if "FINISHED" not in status:
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED,
            "Blender canceled a model import",
            {"path": str(filepath)},
        )


def _rollback_import(before_objects: set[object], before_collections: set[object]) -> None:
    for obj in tuple(bpy.data.objects):
        if obj not in before_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
    for collection in tuple(bpy.data.collections):
        if collection not in before_collections:
            bpy.data.collections.remove(collection, do_unlink=True)


def import_model_files(context: object, paths: tuple[str | Path, ...]) -> ImportBatchResult:
    """Import a validated batch and remove every new object if any file fails."""

    validated = validate_model_paths(paths, require_exists=True)
    before = set(bpy.data.objects)
    before_collections = set(bpy.data.collections)
    try:
        for filepath in validated:
            _run_import(context, filepath)
        imported = tuple(obj for obj in bpy.data.objects if obj not in before)
        if not imported:
            raise DomainError(
                ErrorCode.PRECONDITION_FAILED,
                "The selected files did not create any Blender objects",
            )
        ensure_stable_ids(context.scene.objects)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in imported:
            obj.select_set(True)
        context.view_layer.objects.active = imported[0]
        context.view_layer.update()
        return ImportBatchResult(
            files=tuple(path.name for path in validated),
            object_names=tuple(sorted(obj.name for obj in imported)),
        )
    except DomainError:
        _rollback_import(before, before_collections)
        raise
    except Exception as error:
        _rollback_import(before, before_collections)
        raise DomainError(
            ErrorCode.PRECONDITION_FAILED,
            "Blender could not import the selected model batch",
            {"exception_type": type(error).__name__},
        ) from error
