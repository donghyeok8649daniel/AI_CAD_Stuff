"""Keep parallel CAD views outside visible solids without changing framing."""
import itertools
import math


def reset_clipping(renderer, extra_bounds=()):
    """A parallel camera may zoom into one part while other bodies stay visible.

    ResetCamera(part_bounds) also brings the eye close to that part. Merely
    resetting the near/far planes cannot show solids behind that eye. Moving
    the eye backwards on the same viewing line preserves screen coordinates,
    focal point and parallel scale while keeping all visible bounds in front.
    """
    candidates = [renderer.ComputeVisiblePropBounds(), *extra_bounds]
    candidates = [values for values in candidates
                  if all(math.isfinite(value) for value in values)
                  and all(values[i] <= values[i + 1] for i in (0, 2, 4))]
    if not candidates:
        return
    bounds = [min(values[i] for values in candidates) if i % 2 == 0
              else max(values[i] for values in candidates) for i in range(6)]
    camera = renderer.GetActiveCamera()
    if camera.GetParallelProjection():
        eye = camera.GetPosition()
        direction = camera.GetDirectionOfProjection()
        corners = itertools.product(*[(bounds[i], bounds[i + 1]) for i in (0, 2, 4)])
        nearest = min(sum((point[i] - eye[i]) * direction[i] for i in range(3))
                      for point in corners)
        diagonal = math.sqrt(sum((bounds[i + 1] - bounds[i]) ** 2 for i in (0, 2, 4)))
        margin = max(.001, diagonal * .01)
        if nearest < margin:
            camera.SetPosition(*(eye[i] - direction[i] * (margin - nearest) for i in range(3)))
    renderer.ResetCameraClippingRange(bounds)


def surface_offset(mapper, units=-2):
    """Separate coincident highlights by depth units, never by face slope.

    Slope offsets grow at grazing view angles and can pull a hidden selected
    face through a thin solid. A small constant offset only resolves z-fighting.
    """
    mapper.SetResolveCoincidentTopologyToPolygonOffset()
    mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, units)


def line_offset(mapper):
    mapper.SetResolveCoincidentTopologyToPolygonOffset()
    mapper.SetRelativeCoincidentTopologyLineOffsetParameters(0, -2)
