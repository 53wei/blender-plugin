"""Stable Blender object ID management."""

from __future__ import annotations

from uuid import uuid4

OBJECT_ID_PROPERTY = "bsa_object_id"
LOCK_PROPERTY = "bsa_locked"


def ensure_stable_ids(objects: object) -> None:
    """Assign missing IDs and repair duplicated custom-property UUIDs."""
    seen: set[str] = set()
    for obj in objects:
        object_id = str(obj.get(OBJECT_ID_PROPERTY, ""))
        if not object_id or object_id in seen:
            object_id = str(uuid4())
            obj[OBJECT_ID_PROPERTY] = object_id
        seen.add(object_id)


def stable_id(obj: object) -> str:
    """Return an existing stable object ID."""
    object_id = str(obj.get(OBJECT_ID_PROPERTY, ""))
    if not object_id:
        raise RuntimeError("Object ID was requested before ensure_stable_ids")
    return object_id
