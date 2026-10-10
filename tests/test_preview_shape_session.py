"""Real synthetic previews reuse local BReps without weakening tool geometry."""

from concurrent.futures import ThreadPoolExecutor
import math
from threading import Barrier

import pytest

from cadstudio import kernel
from cadstudio.models import Design, Part


@pytest.fixture(autouse=True)
def clear_persistent_shape_caches():
    assert kernel._local_shape_session.get() is None
    kernel._part_cached.cache_clear()
    kernel._build_cached.cache_clear()
    yield
    assert kernel._local_shape_session.get() is None
    kernel._part_cached.cache_clear()
    kernel._build_cached.cache_clear()


def parameter_parts(count=40):
    return Design(
        parameters={"base_width": "10 mm"},
        parts=[Part(id=f"p{i}", name=f"Parameter plate {i}",
                    geometry=dict(kind="plate", length=10, width=8,
                                  thickness=3, hole_count=0),
                    transform=dict(x=i * 30)) for i in range(count)],
        dimension_bindings=[dict(path=["parts", f"p{i}", "geometry", "length"],
                                 expression=f"base_width + {i} / 10") for i in range(count)],
    )


def assert_real_meshes(result, count):
    assert result["stats"]["valid"] and result["stats"]["parts"] == count
    assert len(result["meshes"]) == count
    for mesh in result["meshes"]:
        assert mesh["valid"] and mesh["solid"] and mesh["volume"] > 0
        assert mesh["vertices"] and mesh["triangles"] and mesh["faces"]
        assert len(mesh["triangle_faces"]) == len(mesh["triangles"]) // 3
        assert max(mesh["triangles"]) < len(mesh["vertices"]) // 3
        assert all("reference" in face for face in mesh["faces"])


def test_preview_reuses_forty_parameter_shapes_across_build_and_face_metadata(monkeypatch):
    design = parameter_parts()
    before = design.model_dump()
    visits = {}
    sessions = []
    original = kernel.local_shape

    def track(design, part, _stack=()):
        shape = original(design, part, _stack)
        visits.setdefault(part.id, []).append(shape)
        sessions.append(kernel._local_shape_session.get())
        return shape

    monkeypatch.setattr(kernel, "local_shape", track)
    result = kernel.preview(design)
    # Forty unique geometries exceed the persistent LRU's capacity of32.
    # The world-build and local-face passes must each use the same BRep.
    assert kernel._part_cached.cache_info().misses == 40
    assert set(visits) == {part.id for part in design.parts}
    assert all(len(shapes) == 2 and shapes[0] is shapes[1] for shapes in visits.values())
    assert all(cache is sessions[0] for cache in sessions) and sessions[0] is not None
    assert sessions[0] == {}  # Owned operation cache releases references on exit.
    assert kernel._part_cached.cache_info().currsize == 32
    assert kernel._local_shape_session.get() is None
    assert_real_meshes(result, 40)
    assert [mesh["volume"] for mesh in result["meshes"]] == pytest.approx(
        [(10 + i / 10) * 8 * 3 for i in range(40)])
    assert result["stats"]["collisions"] == []
    assert design.model_dump() == before


def test_preview_nested_session_keeps_transformed_boolean_tools_in_cache_key():
    raw = parameter_parts().model_dump()
    raw["parts"].extend([
        Part(id="body", name="Rotated cut body",
             geometry=dict(kind="plate", length=20, width=12, thickness=6, hole_count=0),
             transform=dict(x=1200, y=10, z=7, rz=90),
             features=[dict(id="bore", kind="solid", operation="boolean",
                            boolean_mode="cut", tool_part_id="tool")]).model_dump(),
        Part(id="tool", name="Retained bore tool",
             geometry=dict(kind="cylinder", diameter=4, height=10),
             transform=dict(x=1200, y=13, z=5, rz=90)).model_dump(),
    ])
    original = Design.model_validate(raw)
    before = original.model_dump()
    with kernel.local_shape_session():
        owned_by_caller = kernel._local_shape_session.get()
        first = kernel.preview(original)
        original_local = kernel.local_shape(original, original.parts[-2])
        assert kernel._part_cached.cache_info().misses == 42
        moved = original.model_copy(deep=True)
        for part in moved.parts:
            part.transform.x += 1000
            part.transform.y += 50
            part.transform.z += 4
        second = kernel.preview(moved)
        assert kernel._local_shape_session.get() is owned_by_caller and owned_by_caller
        assert kernel.local_shape(moved, moved.parts[-2]) is original_local
        assert kernel._part_cached.cache_info().misses == 42
        changed = moved.model_copy(deep=True)
        changed.parts[-1].transform.y += 6  # Relative bore offset3mm→9mm.
        third = kernel.preview(changed)
        changed_local = kernel.local_shape(changed, changed.parts[-2])
        assert changed_local is not original_local
        assert kernel._part_cached.cache_info().misses == 43
        for result in (first, second, third):
            assert_real_meshes(result, 42)
        expected = 20 * 12 * 6 - math.pi * 2 ** 2 * 6
        assert first["meshes"][-2]["volume"] == pytest.approx(expected)
        assert second["meshes"][-2]["volume"] == pytest.approx(expected)
        assert third["meshes"][-2]["volume"] > expected
        vertices = first["meshes"][-2]["vertices"]
        assert (min(vertices[0::3]), max(vertices[0::3])) == pytest.approx((1194, 1206))
        assert (min(vertices[1::3]), max(vertices[1::3])) == pytest.approx((0, 20))
        assert (min(vertices[2::3]), max(vertices[2::3])) == pytest.approx((7, 13))
    assert owned_by_caller == {} and kernel._local_shape_session.get() is None
    assert original.model_dump() == before


def test_preview_exception_releases_operation_cache_after_world_build(monkeypatch):
    design = parameter_parts()
    before = design.model_dump()
    captured = []

    def fail_at_first_face(*args, **kwargs):
        cache = kernel._local_shape_session.get()
        assert cache is not None and len(cache) == 40
        captured.append(cache)
        raise RuntimeError("synthetic preview face failure")

    monkeypatch.setattr(kernel, "face_frame", fail_at_first_face)
    with pytest.raises(RuntimeError, match="synthetic preview face failure"):
        kernel.preview(design)
    assert len(captured) == 1 and captured[0] == {}
    assert kernel._local_shape_session.get() is None
    assert kernel._part_cached.cache_info().currsize <= 32
    assert design.model_dump() == before


def test_preview_operation_caches_are_thread_local_and_nested_sessions_survive():
    started = Barrier(2)
    rendered = Barrier(2)

    def worker(length):
        design = Design(parts=[Part(id="same_id", name="Thread plate",
            geometry=dict(kind="plate", length=length, width=8, thickness=3, hole_count=0))])
        assert kernel._local_shape_session.get() is None
        with kernel.local_shape_session():
            cache = kernel._local_shape_session.get()
            started.wait(timeout=10)
            result = kernel.preview(design)
            assert kernel._local_shape_session.get() is cache
            rendered.wait(timeout=10)  # Both distinct contexts retain live caches.
            assert len(cache) == 1
            assert_real_meshes(result, 1)
            assert result["meshes"][0]["volume"] == pytest.approx(length * 8 * 3)
        assert cache == {} and kernel._local_shape_session.get() is None
        return cache, result["meshes"][0]["volume"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(worker, 11)
        second = executor.submit(worker, 17)
        a, b = first.result(timeout=20), second.result(timeout=20)
    assert a[0] is not b[0] and a[1] != b[1]
    assert kernel._local_shape_session.get() is None


def test_declared_mechanical_function_reuses_geometry_without_rewriting_part():
    design = parameter_parts(1)
    before = design.model_dump()
    original_shape = kernel.local_shape(design, design.parts[0])
    for function in ("fastener", "joint_support", "actuator", "transmission"):
        declared = design.model_copy(deep=True)
        declared.parts[0].mechanical_function = function
        assert kernel.local_shape(declared, declared.parts[0]) is original_shape
        assert declared.parts[0].mechanical_function == function
        assert declared.model_dump()["parts"][0]["mechanical_function"] == function
    assert kernel._part_cached.cache_info().misses == 1
    changed = design.model_copy(deep=True)
    changed.parts[0].geometry.thickness += 1
    assert kernel.local_shape(changed, changed.parts[0]) is not original_shape
    assert kernel._part_cached.cache_info().misses == 2
    assert design.model_dump() == before
