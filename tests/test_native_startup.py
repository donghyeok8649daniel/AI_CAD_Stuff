import pytest
import native_desktop


def test_startup_failure_keeps_original_exception_and_writes_profile_log(monkeypatch, tmp_path):
    monkeypatch.setenv('CADSTUDIO_DATA_DIR', str(tmp_path))
    def fail(): raise RuntimeError('test startup failure')
    monkeypatch.setattr(native_desktop, 'main', fail)
    with pytest.raises(RuntimeError, match='test startup failure'):
        native_desktop.run()
    log = (tmp_path / 'native-startup-error.log').read_text(encoding='utf-8')
    assert 'RuntimeError: test startup failure' in log and 'NameError' not in log
