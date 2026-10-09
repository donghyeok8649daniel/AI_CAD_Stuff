"""Bounded, per-user Windows integration for native ``*.pcad`` projects.

The native extension gets a normal ProgID and open command. Its default is
assigned only when no existing .pcad default or protected UserChoice exists.
Legacy .cad.json gets a filename-filtered context action without defaulting
JSON to CAD. Existing user choices are never rewritten.
Generic JSON OpenWith and SupportedTypes registrations are deliberately absent:
Windows can choose a lone registered candidate as an implied JSON default.
The registration is opt-in through installation or the application's command.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
from urllib.parse import quote

APP_NAME = 'PromptCADStudio'
FRIENDLY_NAME = 'Prompt CAD Studio'
EXE_NAME = 'PromptCADStudio.exe'
PROGID = 'PromptCADStudio.Project.1'
CAPABILITIES = r'Software\PromptCADStudio\Capabilities'
CLASSES = r'Software\Classes'
APPLICATION = CLASSES + '\\Applications\\' + EXE_NAME
PROJECT = CLASSES + '\\' + PROGID
EXTENSION = '.pcad'
PCAD = CLASSES + '\\' + EXTENSION
OPEN_WITH = PCAD + r'\OpenWithProgids'
LEGACY_OPEN_WITH = CLASSES + r'\.json\OpenWithProgids'
CAD_VERB = CLASSES + r'\SystemFileAssociations\.json\shell\PromptCADStudio.OpenCAD'
REGISTERED_APPS = r'Software\RegisteredApplications'
STATE_KEY = r'Software\PromptCADStudio\FileAssociationRegistration'
STATE_VALUE = 'State'
CAD_FILENAME_QUERY = 'System.FileName:~"*.cad.json"'
DEFAULT_APPS_URI = 'ms-settings:defaultapps?registeredAppUser=' + quote(APP_NAME, safe='')
REG_SZ = 1
SCHEMA = 3


class AssociationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    key: str
    name: str
    value: str


def _executable(executable):
    path = Path(executable).resolve()
    if path.name.casefold() != EXE_NAME.casefold() or not path.is_file():
        raise AssociationError('PromptCADStudio.exe가 들어 있는 설치 폴더에서 실행하세요.')
    if any(character in str(path) for character in ['"', '%', '\r', '\n', '\x00']):
        raise AssociationError('파일 연결에 사용할 수 없는 설치 경로입니다. 따옴표나 %가 없는 폴더를 선택하세요.')
    return path


def registration_plan(executable):
    """Return all intended values without writing to the registry."""
    path = _executable(executable)
    command = f'"{path}" --open "%1"'
    icon = f'"{path}",0'
    return [
        Entry(PROJECT, '', 'Prompt CAD Studio project'),
        Entry(PROJECT, 'FriendlyTypeName', 'Prompt CAD Studio project'),
        Entry(PROJECT + r'\DefaultIcon', '', icon),
        Entry(PROJECT + r'\shell\open\command', '', command),
        Entry(APPLICATION, 'FriendlyAppName', FRIENDLY_NAME),
        Entry(APPLICATION + r'\SupportedTypes', EXTENSION, ''),
        Entry(APPLICATION + r'\shell\open\command', '', command),
        Entry(OPEN_WITH, PROGID, ''),
        Entry(PCAD, '', PROGID),
        Entry(CAPABILITIES, 'ApplicationName', FRIENDLY_NAME),
        Entry(CAPABILITIES, 'ApplicationDescription', 'Open Prompt CAD Studio .pcad projects and legacy .cad.json files.'),
        Entry(CAPABILITIES, 'ApplicationIcon', icon),
        Entry(CAPABILITIES + r'\FileAssociations', EXTENSION, PROGID),
        Entry(REGISTERED_APPS, APP_NAME, CAPABILITIES),
        Entry(CAD_VERB, 'MUIVerb', 'Prompt CAD Studio로 열기'),
        Entry(CAD_VERB, 'Icon', icon),
        Entry(CAD_VERB, 'MultiSelectModel', 'Single'),
        Entry(CAD_VERB, 'AppliesTo', CAD_FILENAME_QUERY),
        Entry(CAD_VERB + r'\command', '', command),
    ]


def _retired_entries():
    # A lone generic JSON OpenWith candidate can become Windows' implied
    # default even without changing its explicit default or UserChoice.
    return [Entry(APPLICATION + r'\SupportedTypes', '.json', ''),
            Entry(LEGACY_OPEN_WITH, PROGID, '')]


def _state_plan(plan, schema):
    if schema == 2:
        return [*plan, *_retired_entries()]
    if schema == SCHEMA:
        return plan
    raise ValueError('Unsupported association ownership schema')


class _WindowsRegistry:
    """All writes are under HKCU; merged defaults and UserChoice are read-only."""
    def __init__(self):
        if os.name != 'nt':
            raise AssociationError('파일 연결 등록은 Windows에서 사용할 수 있습니다.')
        import winreg
        self.registry = winreg

    def get(self, key, name):
        registry = self.registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, key) as handle:
                value, kind = registry.QueryValueEx(handle, name)
                return value, kind
        except FileNotFoundError:
            return None

    def key_exists(self, key):
        registry = self.registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, key):
                return True
        except FileNotFoundError:
            return False

    def merged_default(self, extension):
        registry = self.registry
        try:
            with registry.OpenKey(registry.HKEY_CLASSES_ROOT, extension) as handle:
                value, kind = registry.QueryValueEx(handle, '')
                return value, kind
        except FileNotFoundError:
            return None

    def choice_present(self, extension):
        return self.key_exists('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\' + extension + r'\UserChoice')

    def set(self, key, name, value):
        registry = self.registry
        with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, key, 0, registry.KEY_WRITE) as handle:
            registry.SetValueEx(handle, name, 0, value[1], value[0])

    def delete(self, key, name):
        registry = self.registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, key, 0, registry.KEY_SET_VALUE) as handle:
                registry.DeleteValue(handle, name)
        except FileNotFoundError:
            pass

    def prune_empty(self, key):
        registry = self.registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, key) as handle:
                children, values, _ = registry.QueryInfoKey(handle)
            if not children and not values:
                registry.DeleteKey(registry.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


def _key_candidates(plan):
    """Never prune shared Classes, .json, RegisteredApplications or app data."""
    roots = [PROJECT, APPLICATION, PCAD, LEGACY_OPEN_WITH, CAPABILITIES, CAD_VERB, STATE_KEY]
    keys = {STATE_KEY}
    for entry in plan:
        for root in roots:
            if entry.key == root or entry.key.startswith(root + '\\'):
                suffix = entry.key[len(root):]
                keys.add(root)
                parts = suffix.strip('\\').split('\\') if suffix else []
                for index in range(1, len(parts) + 1):
                    keys.add(root + '\\' + '\\'.join(parts[:index]))
    return sorted(keys, key=lambda key: (key.count('\\'), key))


def _state(backend, plan):
    stored = backend.get(STATE_KEY, STATE_VALUE)
    if stored is None:
        return None
    try:
        if stored[1] != REG_SZ:
            raise ValueError()
        data = json.loads(stored[0])
        if type(data['schema']) is not int:
            raise ValueError()
        owned_plan = _state_plan(plan, data['schema'])
        addresses = {(entry.key, entry.name) for entry in owned_plan}
        required = addresses - {(PCAD, '')}
        records = data['entries']
        stored_addresses = {(record['key'], record['name']) for record in records}
        retired = {(entry.key, entry.name): entry.value for entry in _retired_entries()}
        if (data['app'] != APP_NAME or
                not isinstance(data['executable'], str) or
                len(records) != len(stored_addresses) or
                not required <= stored_addresses <= addresses or
                any(not isinstance(record['value'], str) for record in records) or
                any(record['value'] != retired[record['key'], record['name']]
                    for record in records if (record['key'], record['name']) in retired) or
                not isinstance(data['created_keys'], list) or
                not set(data['created_keys']).issubset(_key_candidates(owned_plan))):
            raise ValueError()
        return data
    except (TypeError, KeyError, ValueError):
        raise AssociationError('기존 CAD 파일 연결의 소유 정보를 확인할 수 없습니다. 설정을 보존했습니다.') from None


def _notify_shell():
    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def _restore(backend, snapshots):
    for key, name, previous in reversed(snapshots):
        if previous is None:
            backend.delete(key, name)
        else:
            backend.set(key, name, previous)


def register(executable, *, _backend=None):
    """Register native .pcad and claim only a currently unassigned default.

    Existing unrelated values in our named slots cause a failure before any
    writes. Re-registration updates an intact registration from another app
    folder. Created-key ownership survives that update. Schema 2's generic
    JSON candidates are retired only when their owned values are unchanged.
    """
    path = _executable(executable)
    plan = registration_plan(path)
    backend = _backend if _backend is not None else _WindowsRegistry()
    old_state = _state(backend, plan)
    expected = {} if old_state is None else {
        (entry['key'], entry['name']): (entry['value'], REG_SZ) for entry in old_state['entries']}
    default_address = (PCAD, '')
    default_owned = bool(default_address in expected and backend.get(*default_address) == expected[default_address])
    protected_choice = backend.choice_present(EXTENSION)
    default_free = bool(backend.merged_default(EXTENSION) is None and not protected_choice)
    # Preserve any pre-existing .pcad default, including a machine-level one.
    # Also preserve a later user edit of a default originally assigned by us.
    if not (default_owned or default_free):
        plan = [entry for entry in plan if (entry.key, entry.name) != default_address]
    for entry in plan:
        if (entry.key, entry.name) == default_address:
            continue
        if backend.get(entry.key, entry.name) != expected.get((entry.key, entry.name)):
            raise AssociationError('기존 파일 연결이 다른 설정과 겹칩니다. 현재 설정을 보존했습니다.')
    original_keys = set(old_state['created_keys']) if old_state else set()
    candidates = set(_key_candidates(plan))
    created_keys = original_keys & candidates
    created_keys.update(key for key in candidates if not backend.key_exists(key))
    state = {'schema': SCHEMA, 'app': APP_NAME, 'executable': str(path),
             'entries': [dict(key=entry.key, name=entry.name, value=entry.value) for entry in plan],
             'created_keys': sorted(created_keys)}
    snapshots = []
    retired_removed = retired_preserved = 0
    try:
        if old_state and old_state['schema'] == 2:
            for entry in _retired_entries():
                current = backend.get(entry.key, entry.name)
                if current == expected[entry.key, entry.name]:
                    snapshots.append((entry.key, entry.name, current))
                    backend.delete(entry.key, entry.name)
                    retired_removed += 1
                elif current is not None:
                    retired_preserved += 1
        for entry in [*plan, Entry(STATE_KEY, STATE_VALUE, json.dumps(state, ensure_ascii=False))]:
            snapshots.append((entry.key, entry.name, backend.get(entry.key, entry.name)))
            backend.set(entry.key, entry.name, (entry.value, REG_SZ))
    except Exception:
        _restore(backend, snapshots)
        for key in reversed(_key_candidates(plan)):
            if key in created_keys:
                backend.prune_empty(key)
        raise
    # Retire only keys created by the old registration and now empty. The
    # shared .json parent and any values changed by the user remain intact.
    for key in sorted(original_keys - candidates, key=lambda key: (key.count('\\'), key), reverse=True):
        try:
            backend.prune_empty(key)
        except OSError:
            pass  # An empty retired key is harmless; owned values are committed.
    if _backend is None:
        _notify_shell()
    return {'registered': True, 'executable': str(path), 'json_default_changed': False,
            'extension': EXTENSION, 'pcad_default_assigned': default_owned or default_free,
            'existing_pcad_default_preserved': protected_choice or not (default_owned or default_free),
            'protected_pcad_userchoice_preserved': protected_choice,
            'userchoice_written': False, 'legacy_json_default_changed': False,
            'legacy_json_general_values_removed': retired_removed,
            'legacy_json_user_edits_preserved': retired_preserved}


def is_registered(executable, *, _backend=None):
    """Check ownership and intact values without opening Settings or writing."""
    path = _executable(executable)
    backend = _backend if _backend is not None else _WindowsRegistry()
    state = _state(backend, registration_plan(path))
    ignored = {(PCAD, '')} | {(entry.key, entry.name) for entry in _retired_entries()}
    return bool(state and Path(state['executable']) == path and all(
        backend.get(entry['key'], entry['name']) == (entry['value'], REG_SZ)
        for entry in state['entries'] if (entry['key'], entry['name']) not in ignored))


def unregister(executable, *, _backend=None):
    """Remove this installation's unchanged values, retaining later user edits."""
    path = _executable(executable)
    plan = registration_plan(path)
    backend = _backend if _backend is not None else _WindowsRegistry()
    state = _state(backend, plan)
    if state is None:
        return {'removed': 0, 'preserved': 0}
    if Path(state['executable']) != path:
        raise AssociationError('다른 설치 폴더의 파일 연결입니다. 현재 연결을 보존했습니다.')
    snapshots = []
    removed = preserved = 0
    try:
        for entry in state['entries']:
            current = backend.get(entry['key'], entry['name'])
            if current == (entry['value'], REG_SZ):
                snapshots.append((entry['key'], entry['name'], current))
                backend.delete(entry['key'], entry['name'])
                removed += 1
            elif current is not None:
                preserved += 1
        snapshots.append((STATE_KEY, STATE_VALUE, backend.get(STATE_KEY, STATE_VALUE)))
        backend.delete(STATE_KEY, STATE_VALUE)
    except Exception:
        _restore(backend, snapshots)
        raise
    for key in reversed(_key_candidates(_state_plan(plan, state['schema']))):
        if key in state['created_keys']:
            backend.prune_empty(key)
    if _backend is None:
        _notify_shell()
    return {'removed': removed, 'preserved': preserved}


def open_default_apps():
    if os.name != 'nt':
        raise AssociationError('Windows 기본 앱 설정은 Windows에서 사용할 수 있습니다.')
    os.startfile(DEFAULT_APPS_URI)


def registration_message():
    return ('Windows에서 .pcad 프로젝트를 Prompt CAD Studio에 연결할 수 있습니다. '
            '기존 .pcad 기본 앱이나 사용자 선택이 있으면 보존하므로 Windows 기본 앱 설정에서 직접 선택하세요. '
            '이전 .cad.json 파일은 우클릭 → Prompt CAD Studio로 열기로 열 수 있습니다. '
            '일반 .json 파일의 기본 앱은 보존합니다.')
