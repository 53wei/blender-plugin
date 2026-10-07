"""Blender extension entry point."""

from __future__ import annotations


def register() -> None:
    """Register the extension UI when Blender enables the add-on."""
    from .bsa.ui import register as register_ui

    register_ui()


def unregister() -> None:
    """Unregister the extension UI when Blender disables the add-on."""
    from .bsa.ui import unregister as unregister_ui

    unregister_ui()
