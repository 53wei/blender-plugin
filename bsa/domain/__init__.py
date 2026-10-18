"""Domain model exports."""

from .actions import (
    ActionPlan,
    LockAction,
    MoveAction,
    PlaceOnAction,
    PreserveTransformConstraint,
    RelativePlaceAction,
    UnlockAction,
)
from .adapter_plate import (
    AdapterPlateDesign,
    AdapterPlateHole,
    AdapterPlateResizePatch,
    AdapterPlateRevision,
    AdapterPlateSpec,
    MountingPatternSpec,
    PatternHoleSpec,
)
from .adapter_plate_mesh import (
    AdapterPlateCreationPlan,
    AdapterPlateMeshSpec,
    AdapterPlateMeshState,
    MeasuredRoundHole,
)
from .enclosure import (
    BoardSpec,
    EnclosureDesign,
    EnclosureIssue,
    EnclosureParameters,
    FdmPrintProfile,
    MountingHoleSpec,
    PortCutout,
    RectangularPortSpec,
)
from .enclosure_preview import (
    EnclosurePartSpec,
    EnclosurePartState,
    EnclosurePreviewPlan,
)
from .errors import DomainError, ErrorCode
from .results import CheckResult, ExecutionResult, VerificationResult
from .scene import BoundingBox, ObjectState, SceneSnapshot

__all__ = [
    "ActionPlan",
    "AdapterPlateDesign",
    "AdapterPlateCreationPlan",
    "AdapterPlateHole",
    "AdapterPlateMeshSpec",
    "AdapterPlateMeshState",
    "AdapterPlateResizePatch",
    "AdapterPlateRevision",
    "AdapterPlateSpec",
    "BoundingBox",
    "BoardSpec",
    "CheckResult",
    "DomainError",
    "ErrorCode",
    "EnclosureDesign",
    "EnclosureIssue",
    "EnclosureParameters",
    "EnclosurePartSpec",
    "EnclosurePartState",
    "EnclosurePreviewPlan",
    "ExecutionResult",
    "FdmPrintProfile",
    "LockAction",
    "MountingHoleSpec",
    "MoveAction",
    "MountingPatternSpec",
    "MeasuredRoundHole",
    "ObjectState",
    "PlaceOnAction",
    "PatternHoleSpec",
    "PreserveTransformConstraint",
    "PortCutout",
    "RectangularPortSpec",
    "RelativePlaceAction",
    "SceneSnapshot",
    "UnlockAction",
    "VerificationResult",
]
