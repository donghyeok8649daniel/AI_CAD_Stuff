from pathlib import Path

import pytest
from cadstudio import file_associations as F


class Registry:
    def __init__(self):
        self.values = {}
        self.keys = set()
        self.fail = None
        self.machine_defaults = {}

    def get(self, key, name):
        return self.values.get((key, name))

    def key_exists(self, key):
        return key in self.keys

    def merged_default(self, extension):
        return self.get(F.CLASSES + '\\' + extension, '') or self.machine_defaults.get(extension)

    def choice_present(self, extension):
        prefix = 'Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\' + extension + r'\UserChoice'
        return self.key_exists(prefix) or any(key == prefix for key, _ in self.values)

    def set(self, key, name, value):
        if self.fail == (key, name):
            self.fail = None
            raise OSError('simulated registry write failure')
        self.keys.add(key)
        self.values[key, name] = value

    def delete(self, key, name):
        self.values.pop((key, name), None)

    def prune_empty(self, key):
        if not any(k == key or k.startswith(key + '\\') for k, _ in self.values):
            self.keys.discard(key)


@pytest.fixture
def executable(tmp_path):
    path = tmp_path / 'CAD 설치 한글 spaces & signs' / F.EXE_NAME
    path.parent.mkdir()
    path.write_bytes(b'unit test executable placeholder')
    return path


def test_native_extension_default_preserves_json_and_nondefault_legacy_action(executable):
    backend = Registry()
    default = (F.CLASSES + r'\.json', '')
    choice = (r'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.json\UserChoice', 'ProgId')
    backend.values[default] = ('ExistingJsonEditor', F.REG_SZ)
    backend.values[choice] = ('ExistingJsonEditor', F.REG_SZ)
    result = F.register(executable, _backend=backend)
    assert result['json_default_changed'] is False
    assert backend.values[default] == backend.values[choice] == ('ExistingJsonEditor', F.REG_SZ)
    assert backend.get(F.CAD_VERB, 'AppliesTo') == ('System.FileName:~"*.cad.json"', F.REG_SZ)
    assert backend.get(F.CAD_VERB, 'DefaultAppliesTo') is None
    assert backend.get(F.PCAD, '') == (F.PROGID, F.REG_SZ)
    assert backend.get(F.CAPABILITIES + r'\FileAssociations', '.pcad') == (F.PROGID, F.REG_SZ)
    assert backend.get(F.CAPABILITIES + r'\FileAssociations', '.json') is None
    assert result['extension'] == '.pcad' and result['pcad_default_assigned']
    assert backend.get(F.CAD_VERB + r'\command', '') == (f'"{executable}" --open "%1"', F.REG_SZ)
    assert F.is_registered(executable, _backend=backend)
    assert not any('.cad.json' in entry.key for entry in F.registration_plan(executable))


@pytest.mark.parametrize('source', ['per_user', 'machine', 'userchoice'])
def test_existing_pcad_default_is_preserved(executable, source):
    backend = Registry()
    choice = (r'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pcad\UserChoice', 'ProgId')
    if source == 'per_user':
        backend.values[F.PCAD, ''] = ('ExistingPCAD', F.REG_SZ)
    elif source == 'machine':
        backend.machine_defaults['.pcad'] = ('MachinePCAD', F.REG_SZ)
    else:
        backend.values[choice] = ('ChosenPCAD', F.REG_SZ)
    before = dict(backend.values)
    result = F.register(executable, _backend=backend)
    assert result['existing_pcad_default_preserved'] and not result['pcad_default_assigned']
    assert result['userchoice_written'] is False
    assert all(backend.values[address] == value for address, value in before.items())
    if source != 'per_user':
        assert backend.get(F.PCAD, '') is None
    assert F.is_registered(executable, _backend=backend)
    F.register(executable, _backend=backend)
    F.unregister(executable, _backend=backend)
    assert backend.values == before


def test_later_pcad_default_change_is_not_reclaimed_on_update(executable):
    backend = Registry()
    F.register(executable, _backend=backend)
    backend.values[F.PCAD, ''] = ('LaterUserChoice', F.REG_SZ)
    assert F.is_registered(executable, _backend=backend)
    result = F.register(executable, _backend=backend)
    assert result['existing_pcad_default_preserved']
    assert backend.get(F.PCAD, '') == ('LaterUserChoice', F.REG_SZ)
    F.unregister(executable, _backend=backend)
    assert backend.values == {(F.PCAD, ''): ('LaterUserChoice', F.REG_SZ)}


def test_later_protected_choice_is_preserved_and_reported_on_update(executable):
    backend = Registry()
    F.register(executable, _backend=backend)
    choice = (r'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pcad\UserChoice', 'ProgId')
    backend.values[choice] = ('LaterChosenPCAD', F.REG_SZ)
    result = F.register(executable, _backend=backend)
    assert result['existing_pcad_default_preserved'] and result['protected_pcad_userchoice_preserved']
    assert backend.values[choice] == ('LaterChosenPCAD', F.REG_SZ)
    F.unregister(executable, _backend=backend)
    assert backend.values == {choice: ('LaterChosenPCAD', F.REG_SZ)}


def test_unregister_preserves_user_changes_and_other_openwith_entries(executable):
    backend = Registry()
    other = (F.OPEN_WITH, 'OtherCAD.Project')
    backend.values[other] = ('', F.REG_SZ)
    F.register(executable, _backend=backend)
    backend.values[F.CAD_VERB, 'Icon'] = ('user icon', F.REG_SZ)
    result = F.unregister(executable, _backend=backend)
    assert result['preserved'] == 1
    assert backend.values == {other: ('', F.REG_SZ), (F.CAD_VERB, 'Icon'): ('user icon', F.REG_SZ)}
    assert F.unregister(executable, _backend=backend) == {'removed': 0, 'preserved': 0}


def test_register_conflict_fails_before_writing(executable):
    backend = Registry()
    backend.values[F.PROJECT, ''] = ('Someone else owns this name', F.REG_SZ)
    before = dict(backend.values)
    with pytest.raises(F.AssociationError, match='겹칩니다'):
        F.register(executable, _backend=backend)
    assert backend.values == before


def test_register_failure_restores_prior_registration(executable, tmp_path):
    backend = Registry()
    F.register(executable, _backend=backend)
    before = dict(backend.values)
    replacement = tmp_path / 'replacement' / F.EXE_NAME
    replacement.parent.mkdir()
    replacement.write_bytes(b'unit test replacement')
    backend.fail = F.CAD_VERB + r'\command', ''
    with pytest.raises(OSError, match='simulated'):
        F.register(replacement, _backend=backend)
    assert backend.values == before
    assert F.is_registered(executable, _backend=backend)


def test_first_registration_failure_leaves_no_values(executable):
    backend = Registry()
    backend.fail = F.CAD_VERB, 'AppliesTo'
    with pytest.raises(OSError):
        F.register(executable, _backend=backend)
    assert backend.values == {}


def test_update_to_new_install_then_old_uninstall_cannot_remove_it(executable, tmp_path):
    backend = Registry()
    F.register(executable, _backend=backend)
    new = tmp_path / 'new installation' / F.EXE_NAME
    new.parent.mkdir()
    new.write_bytes(b'unit test executable placeholder')
    F.register(new, _backend=backend)
    assert F.is_registered(new, _backend=backend)
    with pytest.raises(F.AssociationError, match='다른 설치'):
        F.unregister(executable, _backend=backend)
    assert F.is_registered(new, _backend=backend)
    F.unregister(new, _backend=backend)
    assert backend.values == {}


def test_corrupt_ownership_cannot_delete_arbitrary_registry_paths(executable):
    import json
    backend = Registry()
    F.register(executable, _backend=backend)
    state = json.loads(backend.get(F.STATE_KEY, F.STATE_VALUE)[0])
    state['entries'][0]['key'] = r'Software\OtherApplication'
    backend.values[F.STATE_KEY, F.STATE_VALUE] = (json.dumps(state), F.REG_SZ)
    before = dict(backend.values)
    with pytest.raises(F.AssociationError, match='소유 정보'):
        F.unregister(executable, _backend=backend)
    assert backend.values == before


@pytest.mark.parametrize('folder', ['percent%1', 'percent%PATH%'])
def test_registry_command_rejects_placeholder_characters(tmp_path, folder):
    path = tmp_path / folder / F.EXE_NAME
    path.parent.mkdir()
    path.write_bytes(b'placeholder')
    with pytest.raises(F.AssociationError, match='설치 경로'):
        F.registration_plan(path)


def test_default_app_uri_is_registered_user_app():
    assert F.DEFAULT_APPS_URI == 'ms-settings:defaultapps?registeredAppUser=PromptCADStudio'


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows updater registration')
def test_updater_does_not_opt_in_unregistered_installation(executable, monkeypatch):
    import update_desktop
    calls = []
    monkeypatch.setattr(F, 'is_registered', lambda path: False)
    monkeypatch.setattr(F, 'register', lambda path: calls.append(path))
    result = {'version': '2.24.0'}
    assert update_desktop.refresh_file_registration(executable.parent, result) is result
    assert calls == [] and result == {'version': '2.24.0'}


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows updater registration')
def test_updater_refreshes_only_registered_folder(executable, monkeypatch):
    import update_desktop
    calls = []
    monkeypatch.setattr(F, 'is_registered', lambda path: path == executable)
    monkeypatch.setattr(F, 'register', lambda path: calls.append(path))
    update_desktop.refresh_file_registration(executable.parent, {'version': '2.24.0'})
    assert calls == [executable]


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows updater registration')
def test_registration_warning_does_not_fail_completed_update(executable, monkeypatch):
    import update_desktop
    monkeypatch.setattr(F, 'is_registered', lambda path: True)
    def fail(path):
        raise F.AssociationError('test registry conflict')
    monkeypatch.setattr(F, 'register', fail)
    result = {'version': '2.24.0', 'changed': 5}
    update_desktop.refresh_file_registration(executable.parent, result)
    assert result['version'] == '2.24.0' and result['changed'] == 5
    assert 'test registry conflict' in result['file_association_warning']


@pytest.mark.skipif(__import__('os').name != 'nt', reason='read-only Windows extension API')
def test_windows_extracts_final_extension_from_cad_json():
    import ctypes
    from ctypes import wintypes
    shell = ctypes.WinDLL('shlwapi')
    shell.PathFindExtensionW.argtypes = [wintypes.LPCWSTR]
    shell.PathFindExtensionW.restype = wintypes.LPCWSTR
    assert shell.PathFindExtensionW('assembly.cad.json') == '.json'
    assert shell.PathFindExtensionW('ordinary.json') == '.json'
    assert shell.PathFindExtensionW('assembly.pcad') == '.pcad'
