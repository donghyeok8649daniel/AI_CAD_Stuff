"""Explicit mechanical purpose, independent of shape, motion and readiness.

These declarations do not identify a real product or establish electrical
ratings, mounting adequacy, powered operation or physical assembly readiness.
Legacy parts stay unspecified; names, colors, geometry and joints are never
used to infer a motor or another mechanical function.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Literal, cast


MechanicalFunction = Literal["unspecified", "fastener", "joint_support", "actuator", "transmission"]
FUNCTIONS: tuple[MechanicalFunction, ...] = (
    "unspecified", "fastener", "joint_support", "actuator", "transmission",
)
LABELS = {
    "unspecified": "기계 기능 미지정",
    "fastener": "체결 부품 · 볼트 / 너트 / 고정 핀",
    "joint_support": "수동 관절 지지 구조",
    "actuator": "구동기 · 모터 / 액추에이터",
    "transmission": "동력 전달 부품",
}
ENGLISH_LABELS = {
    "unspecified": "Mechanical function unspecified",
    "fastener": "Fastener · bolt / nut / retaining pin",
    "joint_support": "Passive joint support",
    "actuator": "Actuator · motor / powered actuator",
    "transmission": "Mechanical transmission",
}
GUIDANCE = (
    "mechanical_function is an explicit purpose declaration, separate from role/colors and joint motion: "
    "fastener=bolts/nuts/retaining pins; joint_support=passive joint supports/housings/bushings; "
    "actuator=an explicitly specified motor or powered actuator; transmission=shafts/gears/motion transfer. "
    "Use unspecified when the purpose is unknown. Never infer a powered actuator from a part name, "
    "color, cylinder/coaxial geometry or a movable joint. A joint constraint creates no motor or hardware. "
    "The declaration does not prove product identity, physical readiness or powered operation, and "
    "never supplies voltage/current/torque ratings or creates an electrical registration."
)


def validate_mechanical_function(value: object) -> MechanicalFunction:
    """Validate an explicit declaration before changing a saved part."""
    if not isinstance(value, str) or value not in FUNCTIONS:
        raise ValueError("알 수 없는 기계 기능입니다.")
    return cast(MechanicalFunction, value)


def mechanical_function(part: object) -> MechanicalFunction:
    """Classify only the saved field; missing legacy fields remain unspecified."""
    value = part.get("mechanical_function", "unspecified") if isinstance(part, Mapping) else getattr(part, "mechanical_function", "unspecified")
    return validate_mechanical_function(value)


def function_label(value: object, *, language: str = "ko") -> str:
    value = validate_mechanical_function(value)
    if language not in ("ko", "en"):
        raise ValueError("기계 기능 표시 언어는 ko 또는 en이어야 합니다.")
    return (ENGLISH_LABELS if language == "en" else LABELS)[value]


def assign_mechanical_function(part: MutableMapping, value: object) -> None:
    """Change only this field; clearing it preserves the legacy representation."""
    value = validate_mechanical_function(value)
    if value == "unspecified":
        part.pop("mechanical_function", None)
    else:
        part["mechanical_function"] = value
