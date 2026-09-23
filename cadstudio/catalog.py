"""Shared defaults and Korean field metadata for UI and prompt interpretation."""
import math

from .models import Design, GEOMETRY_TYPES, Part, Transform

TITLES = {
    "round_specimen": "원통형 시편", "flat_specimen": "평판형 시편", "wafer": "웨이퍼",
    "link": "양단 링크", "plate": "구멍판", "bracket": "L 브래킷", "cylinder": "원통 · 튜브",
    "robot_arm": "2링크 조립", "extrusion": "스케치 돌출",
    "sweep":"스윕", "loft":"로프트",
    "revolve":"회전", "imported":"가져온 부품",
}
FIELDS = {
    "length": ("전체 길이", "mm"), "gauge_length": ("평행부 길이", "mm"),
    "grip_diameter": ("그립 직경", "mm"), "gauge_diameter": ("목 직경", "mm"),
    "transition_length": ("전이 길이 (한쪽)", "mm"), "grip_width": ("그립 폭", "mm"),
    "gauge_width": ("목 폭", "mm"), "thickness": ("두께", "mm"),
    "diameter": ("직경", "mm"), "flat_depth": ("플랫 깊이", "mm"), "width": ("폭", "mm"),
    "hole_diameter": ("구멍 직경", "mm"), "hole_spacing": ("구멍 중심 간격", "mm"),
    "hole_count": ("구멍 수", "개"), "hole_pitch_x": ("X 구멍 간격", "mm"),
    "hole_pitch_y": ("Y 구멍 간격", "mm"), "height": ("높이", "mm"),
    "hole_inset": ("구멍 가장자리 거리", "mm"), "bore_diameter": ("내경 (0 = 막힘)", "mm"),
}
EXAMPLES = {
    "round_specimen": "원통형 시편 전체 길이 100, 목 직경 8, 그립 직경 16, 평행부 길이 30, 전이 길이 15 mm",
    "flat_specimen": "평판형 시편 전체 길이 120, 목 폭 10, 그립 폭 25, 두께 3 mm",
    "wafer": "웨이퍼 직경 100 mm, 두께 525 um, 플랫 깊이 3 mm",
    "link": "링크 길이 110, 폭 24, 두께 6, 구멍 직경 8, 구멍 간격 80 mm",
    "bracket": "브래킷 길이 60, 폭 40, 높이 50, 두께 5, 구멍 직경 6 mm",
    "plate": "구멍판 길이 80, 폭 60, 두께 6, 구멍 수 4, X 간격 56, Y 간격 36 mm",
    "cylinder": "튜브 직경 30, 높이 20, 내경 20 mm",
    "robot_arm": "2링크 로봇 조립", "extrusion": "스케치 돌출 두께 8 mm",
    "sweep":"원형 단면 경로 스윕", "loft":"두 단면 사이 로프트",
}


def part_default(kind, identifier="part-1", name=None):
    return Part(id=identifier, name=name or TITLES[kind], geometry=GEOMETRY_TYPES[kind]())


def preset(kind):
    if kind == "robot_arm":
        a, b = math.radians(25), math.radians(-30)
        end = (94 * math.cos(a), 94 * math.sin(a))
        parts = [
            Part(id="base", name="베이스", geometry={"kind": "cylinder", "diameter": 50, "height": 10, "bore_diameter": 8}, color="#667b89"),
            Part(id="link-1", name="링크 1", geometry={"kind": "link", "length": 120, "width": 26, "thickness": 8, "hole_diameter": 8.4, "hole_spacing": 94}, transform=Transform(x=47*math.cos(a), y=47*math.sin(a), z=10, rz=25), color="#70aebf"),
            Part(id="link-2", name="링크 2", geometry={"kind": "link", "length": 100, "width": 24, "thickness": 8, "hole_diameter": 8.4, "hole_spacing": 76}, transform=Transform(x=end[0]+38*math.cos(b), y=end[1]+38*math.sin(b), z=19, rz=-30), color="#d6ad70"),
            Part(id="pin-1", name="어깨 핀", geometry={"kind": "cylinder", "diameter": 8, "height": 20}, color="#c4cdd4"),
            Part(id="pin-2", name="팔꿈치 핀", geometry={"kind": "cylinder", "diameter": 8, "height": 19}, transform=Transform(x=end[0], y=end[1], z=9), color="#c4cdd4"),
        ]
        parts[0].fixed = True
        return Design(name="2링크 로봇 조립", mode="robot", parts=parts, mates=[
            dict(id="shoulder", kind="revolute", parent="base", child="link-1", parent_anchor="top", child_anchor="hole_1_bottom", rz=25),
            dict(id="elbow", kind="revolute", parent="link-1", child="link-2", parent_anchor="hole_2_top", child_anchor="hole_1_bottom", z=1, rz=-55),
            dict(id="shoulder-pin", kind="rigid", parent="base", child="pin-1"),
            dict(id="elbow-pin", kind="rigid", parent="link-1", child="pin-2", parent_anchor="hole_2_bottom", z=-1),
        ])
    return Design(name=TITLES[kind], mode="specimen" if kind in {"round_specimen", "flat_specimen", "wafer"} else "robot", parts=[part_default(kind)])


def catalog():
    items = []
    for kind in [*GEOMETRY_TYPES, "robot_arm"]:
        design = preset(kind)
        params = []
        if kind != "robot_arm":
            for key, value in design.parts[0].geometry.model_dump().items():
                if key not in FIELDS:
                    continue
                label, unit = FIELDS[key]
                params.append({"key": key, "label": label, "unit": unit, "default": value})
        items.append({"kind": kind, "title": TITLES[kind], "mode": design.mode, "fields": params, "example": EXAMPLES[kind], "design": design.model_dump()})
    return items

TITLES['sheetmetal']='판금 · 단일 절곡'
