"""The source/frozen package check is independent of pytest and fixture paths."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cadstudio.flexible_wire_package_check import run


def test_bounded_package_check_writes_truthful_receipt_and_preserves_existing_report(tmp_path):
    output = tmp_path / 'package-check.json'
    # Match the CLI contract and stay independent of any native QApplication
    # that another test in the same pytest process may already have created.
    result = subprocess.run([sys.executable, '-c',
        'import sys; from cadstudio.flexible_wire_package_check import run; raise SystemExit(run(sys.argv[1]))',
        str(output)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    before = output.read_bytes()
    report = json.loads(before)
    assert report['success'] and report['count'] >= 17
    assert all(check['passed'] for check in report['checks'])
    assert report['user_project_reads'] == report['original_projects_modified'] == 0
    assert report['VTK_render_calls'] == 0 and report['native_window_shown'] is False
    assert report['hardware_IO'] is False and report['physical_or_electrical_qualification'] is False
    with pytest.raises(FileExistsError):
        run(output)
    assert output.read_bytes() == before
