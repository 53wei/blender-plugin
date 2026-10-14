"""Transactional Blender camera application and PNG rendering."""

from __future__ import annotations

from pathlib import Path

import bpy
from mathutils import Matrix, Vector

from ..core.camera_framing import CameraFramePlan
from ..domain.errors import DomainError, ErrorCode


def apply_camera_frame_plan(scene: object, plan: CameraFramePlan) -> object:
    """Create or move the active camera and restore its state after any failure."""

    previous_active = scene.camera
    camera_object = (
        previous_active
        if previous_active and previous_active.type == "CAMERA"
        else None
    )
    created = camera_object is None
    previous_matrix = camera_object.matrix_world.copy() if camera_object else None
    previous_lens = float(camera_object.data.lens) if camera_object else None
    previous_sensor = float(camera_object.data.sensor_width) if camera_object else None
    previous_clip = (
        (float(camera_object.data.clip_start), float(camera_object.data.clip_end))
        if camera_object
        else None
    )
    created_data = None
    try:
        if camera_object is None:
            camera_data = bpy.data.cameras.new("场景领航员相机")
            created_data = camera_data
            camera_object = bpy.data.objects.new("场景领航员相机", camera_data)
            scene.collection.objects.link(camera_object)
        location = Vector(plan.camera_location)
        target = Vector(plan.target)
        direction = target - location
        if direction.length <= 1e-9:
            raise DomainError(ErrorCode.PRECONDITION_FAILED, "Camera cannot overlap its target")
        camera_object.location = location
        camera_object.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        camera_object.data.lens = plan.lens_mm
        camera_object.data.sensor_width = plan.sensor_width_mm
        camera_object.data.clip_start = plan.clip_start
        camera_object.data.clip_end = plan.clip_end
        scene.camera = camera_object
        bpy.context.view_layer.update()

        forward = camera_object.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
        if forward.angle(direction.normalized()) > 1e-4:
            raise DomainError(ErrorCode.POSTCONDITION_FAILED, "Camera look-at verification failed")
        if abs(float(camera_object.data.lens) - plan.lens_mm) > 1e-6:
            raise DomainError(ErrorCode.POSTCONDITION_FAILED, "Camera lens verification failed")
        return camera_object
    except Exception:
        if created and camera_object is not None:
            bpy.data.objects.remove(camera_object, do_unlink=True)
            if created_data is not None and created_data.users == 0:
                bpy.data.cameras.remove(created_data)
        elif camera_object is not None and previous_matrix is not None:
            camera_object.matrix_world = Matrix(previous_matrix)
            camera_object.data.lens = previous_lens
            camera_object.data.sensor_width = previous_sensor
            camera_object.data.clip_start, camera_object.data.clip_end = previous_clip
        scene.camera = previous_active
        bpy.context.view_layer.update()
        raise


def render_camera_png(
    scene: object,
    filepath: str | Path,
    *,
    resolution_x: int,
    resolution_y: int,
    transparent: bool,
) -> Path:
    """Render one PNG while restoring every temporary render setting."""

    if scene.camera is None:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Create or select a camera first")
    if not 64 <= resolution_x <= 8192 or not 64 <= resolution_y <= 8192:
        raise DomainError(ErrorCode.PRECONDITION_FAILED, "Render size must be 64 to 8192 pixels")
    output = Path(filepath).expanduser()
    if output.suffix.lower() != ".png":
        output = output.with_suffix(".png")
    output.parent.mkdir(parents=True, exist_ok=True)
    render = scene.render
    previous = (
        render.filepath,
        render.image_settings.file_format,
        render.resolution_x,
        render.resolution_y,
        render.resolution_percentage,
        render.film_transparent,
    )
    try:
        render.filepath = str(output)
        render.image_settings.file_format = "PNG"
        render.resolution_x = resolution_x
        render.resolution_y = resolution_y
        render.resolution_percentage = 100
        render.film_transparent = transparent
        bpy.ops.render.render(write_still=True)
    except Exception as error:
        raise DomainError(
            ErrorCode.INTERNAL_ERROR,
            "Blender could not render the PNG",
            {"exception_type": type(error).__name__},
        ) from error
    finally:
        (
            render.filepath,
            render.image_settings.file_format,
            render.resolution_x,
            render.resolution_y,
            render.resolution_percentage,
            render.film_transparent,
        ) = previous
    if not output.is_file():
        raise DomainError(ErrorCode.POSTCONDITION_FAILED, "PNG file was not created")
    return output
