from cadstudio.profile_paths import LEGACY_PUBLIC_PROFILE, default_data_dir


def test_explicit_profile_wins(tmp_path):
    previous = tmp_path / LEGACY_PUBLIC_PROFILE
    previous.mkdir()
    assert default_data_dir(environ={'CADSTUDIO_DATA_DIR': str(tmp_path / 'isolated')},
                            executable=tmp_path / 'PromptCADStudio.exe', frozen=True) == tmp_path / 'isolated'


def test_installed_previous_public_profile_continues(tmp_path):
    previous = tmp_path / LEGACY_PUBLIC_PROFILE
    previous.mkdir()
    marker = previous / 'user-setting'
    marker.write_bytes(b'preserved')
    assert default_data_dir(environ={'LOCALAPPDATA': str(tmp_path / 'local')},
                            executable=tmp_path / 'PromptCADStudio.exe', frozen=True) == previous
    assert marker.read_bytes() == b'preserved'


def test_new_install_and_source_use_standard_profile(tmp_path):
    previous = tmp_path / LEGACY_PUBLIC_PROFILE
    previous.mkdir()
    env = {'LOCALAPPDATA': str(tmp_path / 'local')}
    assert default_data_dir(environ=env, executable=tmp_path / 'other' / 'PromptCADStudio.exe', frozen=True) == tmp_path / 'local' / 'PromptCADStudio'
    assert default_data_dir(environ=env, executable=tmp_path / 'PromptCADStudio.exe', frozen=False) == tmp_path / 'local' / 'PromptCADStudio'
