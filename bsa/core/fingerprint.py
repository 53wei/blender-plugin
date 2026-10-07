"""Stable scene fingerprint generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from ..domain.scene import ObjectState, SceneSnapshot


def _normalized_object(obj: ObjectState) -> dict[str, object]:
    return {
        "object_id": obj.object_id,
        "matrix_world": [round(value, 9) for value in obj.matrix_world],
        "dimensions": [round(value, 9) for value in obj.dimensions_world],
        "locked": obj.locked,
    }


def fingerprint_objects(objects: Iterable[ObjectState]) -> str:
    """Hash the plan-relevant stable state of objects sorted by ID."""
    payload = [_normalized_object(obj) for obj in sorted(objects, key=lambda item: item.object_id)]
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_snapshot(snapshot: SceneSnapshot, object_ids: Iterable[str] | None = None) -> str:
    """Fingerprint all objects or an explicit relevant subset."""
    if object_ids is None:
        return fingerprint_objects(snapshot.objects)
    indexed = snapshot.object_map()
    selected = [indexed[object_id] for object_id in sorted(set(object_ids))]
    return fingerprint_objects(selected)
