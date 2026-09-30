"""The empty native workspace should not load numerical solvers before use."""

import subprocess
import sys
from pathlib import Path


def test_native_startup_defers_scipy_until_a_matching_cad_operation():
    # A fresh process matters: other tests may have already imported SciPy.
    script = """
import math
import sys

import cadstudio.native.window
from cadstudio.models import Design, Extrusion, Transform
from cadstudio.constraints import solve_sketch, transform_matrix
from cadstudio.sketch_engine import spline_curve

assert not any(name.startswith('scipy.') for name in sys.modules), 'blank native import loaded SciPy'
Design()
Extrusion(points=[{'x': 0, 'y': 0}, {'x': 10, 'y': 0},
                  {'x': 10, 'y': 10}, {'x': 0, 'y': 10}])
assert 'scipy.optimize' not in sys.modules, 'unconstrained design loaded optimizer'

points = [type('Point', (), {'x': 1., 'y': 2.})(),
          type('Point', (), {'x': 5., 'y': 2.})()]
fixed = type('Constraint', (), {'kind': 'fixed', 'a': 0, 'b': 1,
                                'x': 0., 'y': 0., 'value': 0.})()
solved, status = solve_sketch(points, [fixed])
assert status['max_error'] < 1e-5 and abs(solved[0][0]) < 1e-5
assert 'scipy.optimize' in sys.modules, 'constraint solver did not load optimizer'

matrix = transform_matrix(Transform(rz=90))
assert abs(matrix[0, 1] + 1) < 1e-10 and abs(matrix[1, 0] - 1) < 1e-10
assert 'scipy.spatial.transform' in sys.modules, 'rotation did not load transform'

curve = spline_curve((0., 0., 10., 0., 20., 10., 30., 0.), 'fit', False)
assert math.isfinite(float(curve(.5)[0])) and math.isfinite(float(curve(.5)[1]))
assert 'scipy.interpolate' in sys.modules, 'spline did not load interpolator'
"""
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run([sys.executable, "-c", script], cwd=root,
                         capture_output=True, text=True, timeout=35)
    assert run.returncode == 0, run.stdout + run.stderr
