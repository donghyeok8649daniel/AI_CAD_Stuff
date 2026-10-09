"""Portable firmware candidates are bounded source data, never executables.

The trusted CAD process records identity and wiring fingerprints. A saved
candidate may become stale after an edit; that is reported when reviewed or
applied, rather than breaking project load or history replay.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Literal
import unicodedata
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

MAX_FILE_BYTES = 256 * 1024
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_FILES = 32
MANIFEST_NAME = 'firmware-bundle.json'
FirmwareTarget = Literal['raspberry_python', 'arduino', 'stm32_hal']
SOURCE_SUFFIXES = {'.py', '.c', '.cpp', '.h', '.hpp', '.ino'}
_FORBIDDEN_DIRECTORIES = {'.git', '.hg', '.svn', '.vscode', '.idea'}
_PROGRAMMABLE_PRODUCTS = {'st_b_g431b_esc1'}
_TARGETS = {
    'rpi3bplus': ('raspberry_python',), 'rpi4b': ('raspberry_python',),
    'rpi_zero2w': ('raspberry_python',),
    'arduino_uno_r3': ('arduino',), 'arduino_mega2560_r3': ('arduino',),
    'nucleo_f401re': ('stm32_hal',), 'nucleo_f446re': ('stm32_hal',),
    'nucleo_f103rb': ('stm32_hal',), 'st_nucleo_g474re': ('stm32_hal',),
    'st_b_g431b_esc1': ('stm32_hal',),
    # Arduino core availability remains a missing build dependency. Pico code
    # is not Raspberry Pi OS Python or STM32 HAL.
    'rpi_pico': ('arduino',), 'rpi_pico2': ('arduino',),
}


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


def _canonical(value):
    if isinstance(value, BaseModel):
        # Fingerprints compare semantic operating state, independently of
        # legacy serializers' absent-versus-explicit-default history spelling.
        return {key: _canonical(getattr(value, key)) for key in type(value).model_fields}
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _digest(value) -> str:
    return sha256(json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _without_reference_urls(value):
    if isinstance(value, dict):
        return {key: _without_reference_urls(item) for key, item in value.items() if key != 'source_url'}
    if isinstance(value, list):
        return [_without_reference_urls(item) for item in value]
    return value


def validate_relative_path(value: str) -> str:
    """One canonical relative filename spelling, including Windows aliases."""
    if (not isinstance(value, str) or not value or len(value) > 240 or
            unicodedata.normalize('NFC', value) != value or '\\' in value or
            any(ord(c) < 32 or c in '<>:"|?*' for c in value)):
        raise ValueError('Firmware paths must be canonical, safe relative filenames.')
    path = PurePosixPath(value)
    parts = value.split('/')
    if path.is_absolute() or len(parts) > 8 or any(not part or part in ('.', '..') for part in parts):
        raise ValueError('Absolute, empty and traversal firmware paths are not allowed.')
    for part in parts:
        stem = part.split('.')[0].upper()
        if (part[-1] in '. ' or part[0] in '-@' or part.casefold() in _FORBIDDEN_DIRECTORIES or
                re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])', stem)):
            raise ValueError('Reserved or ambiguous firmware filenames are not allowed.')
    if value.casefold() == MANIFEST_NAME:
        raise ValueError('The firmware manifest filename is reserved.')
    return value


class FirmwareBinding(_Model):
    board_component_id: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    part_id: str = Field(default='', max_length=40, pattern=r'^[A-Za-z0-9_-]*$')
    catalog_id: str = Field(min_length=1, max_length=100)
    pinout_catalog_id: str = Field(default='', max_length=100)
    board_model: str = Field(min_length=1, max_length=180)
    board_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    wiring_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    pin_map_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class FirmwareFile(_Model):
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=MAX_FILE_BYTES)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    role: Literal['source', 'documentation', 'configuration'] = 'source'

    @model_validator(mode='after')
    def safe_source_data(self):
        validate_relative_path(self.path)
        suffix = PurePosixPath(self.path).suffix.lower()
        allowed = (SOURCE_SUFFIXES if self.role == 'source' else
                   {'.md', '.txt'} if self.role == 'documentation' else {'.json'})
        if suffix not in allowed:
            raise ValueError('Firmware files may contain sources, Markdown/text documentation or JSON data only.')
        raw = self.content.encode('utf-8')
        if len(raw) > MAX_FILE_BYTES or '\x00' in self.content:
            raise ValueError('Each firmware file must be NUL-free UTF-8 text within 256 KiB.')
        if sha256(raw).hexdigest() != self.sha256:
            raise ValueError('Firmware source identity does not match its SHA-256.')
        if self.role == 'configuration':
            try:
                json.loads(self.content, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, RecursionError) as exc:
                raise ValueError('Firmware configuration must be valid finite JSON data.') from exc
        return self


class FirmwarePinBinding(_Model):
    pin: str = Field(min_length=1, max_length=48, pattern=r'^[A-Za-z0-9_-]+$')
    node: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    function: str = Field(default='', max_length=160)


class FirmwareGenerationProvenance(_Model):
    request: str = Field(max_length=16384)
    provider: Literal['codex'] = 'codex'
    model: str = Field(min_length=1, max_length=160)
    effort: str = Field(default='', max_length=32)
    created_utc: datetime
    attempts: int = Field(ge=1, le=1_000_000_000)

    @field_serializer('created_utc')
    def portable_timestamp(self, value: datetime) -> str:
        # Document history uses Python-mode dumps as JSON values. Keep the
        # timestamp textual in both modes while retaining datetime validation.
        return value.isoformat().replace('+00:00', 'Z')

    @model_validator(mode='after')
    def trusted_record_shape(self):
        if self.created_utc.utcoffset() != timedelta(0):
            raise ValueError('Firmware generation provenance requires a timezone-aware UTC timestamp.')
        if len(self.request.encode('utf-8')) > 16384 or '\x00' in self.request or '\x00' in self.model:
            raise ValueError('Firmware request metadata must be bounded UTF-8 text.')
        return self


class FirmwareBundle(_Model):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=160)
    target: FirmwareTarget
    binding: FirmwareBinding
    files: list[FirmwareFile] = Field(min_length=1, max_length=MAX_FILES)
    entrypoint: str = Field(min_length=1, max_length=240)
    notes: str = Field(default='', max_length=16384)
    missing_parameters: list[str] = Field(default_factory=list, max_length=64)
    pin_bindings: list[FirmwarePinBinding] = Field(default_factory=list, max_length=144)
    generation: FirmwareGenerationProvenance | None = None

    @model_validator(mode='after')
    def bounded_portable_candidate(self):
        validate_relative_path(self.entrypoint)
        if len(self.model_dump_json().encode('utf-8')) > MAX_BUNDLE_BYTES:
            raise ValueError('A portable firmware candidate must remain within 2 MiB.')
        paths = {file.path.casefold(): file for file in self.files}
        if len(paths) != len(self.files):
            raise ValueError('Firmware paths must be unique, including case-insensitive aliases.')
        for path in paths:
            if any('/'.join(path.split('/')[:i]) in paths for i in range(1, len(path.split('/')))):
                raise ValueError('A firmware file cannot also be a directory.')
        entry = next((file for file in self.files if file.path == self.entrypoint), None)
        expected = {'.py'} if self.target == 'raspberry_python' else {'.ino', '.cpp', '.c'} if self.target == 'arduino' else {'.c', '.cpp'}
        if entry is None or entry.role != 'source' or PurePosixPath(entry.path).suffix.lower() not in expected:
            raise ValueError('The entrypoint must be an existing source file for the selected target.')
        if len({item.pin for item in self.pin_bindings}) != len(self.pin_bindings):
            raise ValueError('Firmware pin assignments cannot be duplicated.')
        if any(not value or len(value) > 1000 or '\x00' in value for value in self.missing_parameters):
            raise ValueError('Missing firmware parameters must be short, nonempty text.')
        return self


class BindingIssue(_Model):
    code: str
    message: str


class FirmwareBindingReport(_Model):
    status: Literal['current', 'stale', 'missing_board', 'unsupported_board']
    issues: list[BindingIssue] = Field(default_factory=list)


def _workspace(raw):
    # Lazy import keeps persisted bundle models independent of the electrical
    # model which stores them; it also permits exact legacy field omission.
    from .electrical import ElectricalWorkspace
    return ElectricalWorkspace.model_validate(raw.model_dump() if isinstance(raw, ElectricalWorkspace) else raw)


def _reference(component):
    from .board_pins import board_pinout
    from .product_diagrams import product_diagram
    board = board_pinout(component.catalog_id)
    if component.kind == 'mcu' and board is not None:
        return board, board.pins
    if component.catalog_id in _PROGRAMMABLE_PRODUCTS and component.kind in ('mcu', 'load'):
        product = product_diagram(component.catalog_id)
        if product is not None:
            return product, product.terminals
    return None, ()


def programmable_board_ids(workspace) -> list[str]:
    return [item.id for item in _workspace(workspace).components
            if _reference(item)[0] is not None and supported_targets(item.catalog_id)
            and _registered_target(item)]


def supported_targets(catalog_id: str) -> tuple[str, ...]:
    return _TARGETS.get(catalog_id, ())


def _registered_target(component):
    return (component.part_registration and bool(component.part_id) and
            (component.product_pinout_catalog_id == component.catalog_id
             if component.catalog_id in _PROGRAMMABLE_PRODUCTS else
             component.pinout_catalog_id == component.catalog_id))


def create_binding(workspace, board_id: str) -> FirmwareBinding:
    work = _workspace(workspace)
    component = next((item for item in work.components if item.id == board_id), None)
    if component is None:
        raise ValueError('The selected firmware board is not registered in this circuit.')
    reference, pins = _reference(component)
    if reference is None:
        raise ValueError('Select an exact registered programmable board with documented pins or terminals.')
    if not _registered_target(component):
        raise ValueError('Register the actual CAD part as this exact board and confirm its documented pin or product-terminal map before firmware generation.')
    def operating_data(item):
        value = _without_reference_urls(_canonical(item))
        # Labels, drawing placement and descriptive links do not alter code
        # connectivity. All declared circuit operating values do.
        value.pop('name', None); value.pop('wire_color', None)
        return value
    wiring = {'nodes': sorted(work.nodes),
              'components': sorted((operating_data(item) for item in work.components), key=lambda value: value['id']),
              'force_chain': _without_reference_urls(_canonical(work.force_chain)) if work.force_chain is not None else None}
    return FirmwareBinding(board_component_id=component.id, part_id=component.part_id,
        catalog_id=component.catalog_id, pinout_catalog_id=component.pinout_catalog_id or component.product_pinout_catalog_id,
        board_model=reference.model, board_sha256=_digest(operating_data(component)),
        wiring_sha256=_digest(wiring), pin_map_sha256=_digest([asdict(pin) for pin in pins]))


def verify_bundle_binding(bundle: FirmwareBundle | dict, workspace) -> FirmwareBindingReport:
    bundle = FirmwareBundle.model_validate(bundle.model_dump() if isinstance(bundle, FirmwareBundle) else bundle)
    work = _workspace(workspace)
    component = next((item for item in work.components if item.id == bundle.binding.board_component_id), None)
    if component is None:
        return FirmwareBindingReport(status='missing_board', issues=[BindingIssue(code='missing_board', message='The bound firmware board was removed. Rebind the candidate explicitly.')])
    reference, pins = _reference(component)
    if reference is None:
        return FirmwareBindingReport(status='unsupported_board', issues=[BindingIssue(code='unsupported_board', message='The current board has no verified programmable target reference.')])
    if bundle.target not in supported_targets(component.catalog_id):
        return FirmwareBindingReport(status='unsupported_board', issues=[BindingIssue(code='target_mismatch', message='The selected source family does not match this exact board. Pico Arduino candidates require their own board core; they are not Pi OS Python.')])
    if not _registered_target(component):
        return FirmwareBindingReport(status='stale', issues=[BindingIssue(code='registration_changed', message='The CAD-part registration or exact documented board map changed. Review and register the board again.')])
    current = create_binding(work, component.id)
    issues = []
    if current != bundle.binding:
        issues.append(BindingIssue(code='stale_binding', message='Board, pins or saved wiring changed after generation. Regenerate or explicitly review and rebind this candidate.'))
    known = {pin.key for pin in pins}
    mapping = {**component.signal_pins, **component.terminal_pins, **component.board_supply_pins}
    for assignment in bundle.pin_bindings:
        if assignment.pin not in known or mapping.get(assignment.pin) != assignment.node:
            issues.append(BindingIssue(code='pin_binding_mismatch', message=f'{assignment.pin}: firmware assignment does not match the documented pin and saved board-to-net connection.'))
    return FirmwareBindingReport(status='stale' if issues else 'current', issues=issues)


def create_bundle(name, target, workspace, board_id, files, entrypoint, *, notes='',
                  missing_parameters=(), pin_bindings=(), generation=None) -> FirmwareBundle:
    sources = []
    for file in files:
        if isinstance(file, FirmwareFile):
            data = {'path': file.path, 'content': file.content, 'role': file.role}
        else:
            data = dict(file)
        if set(data) - {'path', 'content', 'role'}:
            raise ValueError('Generated files may provide path, content and role only; source hashes are recorded by CAD.')
        content = data['content']
        sources.append(FirmwareFile(**data, sha256=sha256(content.encode('utf-8')).hexdigest()))
    candidate = FirmwareBundle(id='fw_'+uuid4().hex[:24], name=name, target=target,
        binding=create_binding(workspace, board_id), files=sources, entrypoint=entrypoint,
        notes=notes, missing_parameters=list(missing_parameters), pin_bindings=list(pin_bindings),
        generation=generation)
    report = verify_bundle_binding(candidate, workspace)
    if report.status != 'current':
        raise ValueError('\n'.join(issue.message for issue in report.issues))
    return candidate


def to_program_attachment(bundle: FirmwareBundle | dict, workspace):
    """Explicitly attach only the entrypoint for the limited GPIO trace parser."""
    from .program_attachment import ProgramAttachment
    bundle = FirmwareBundle.model_validate(bundle.model_dump() if isinstance(bundle, FirmwareBundle) else bundle)
    report = verify_bundle_binding(bundle, workspace)
    if report.status != 'current':
        raise ValueError('Review the stale firmware binding before attaching a program.')
    component = next(item for item in _workspace(workspace).components if item.id == bundle.binding.board_component_id)
    if component.kind != 'mcu':
        raise ValueError('An ESC firmware bundle is stored and exported separately. The limited GPIO trace attachment requires an MCU / MPU board.')
    entry = next(file for file in bundle.files if file.path == bundle.entrypoint)
    return ProgramAttachment(name=PurePosixPath(entry.path).name, language=bundle.target,
        source=entry.content, sha256=entry.sha256, board_component_id=bundle.binding.board_component_id)


class FirmwareExportCancelled(InterruptedError):
    pass


def _check_cancelled(cancelled):
    if cancelled():
        raise FirmwareExportCancelled('Firmware export was cancelled; no destination was published.')


def _reject_reparse(path: Path):
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Firmware export cannot cross symbolic links, junctions or reparse points.')


def _rename_new_directory(source: Path, target: Path):
    """Atomic publication without replacing a concurrently created folder."""
    if os.name == 'nt':
        os.rename(source, target)  # Windows rename never replaces a directory.
        return
    import ctypes
    import sys
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        function = libc.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        outcome = function(-100, os.fsencode(source), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
    elif sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        function = libc.renamex_np
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        outcome = function(os.fsencode(source), os.fsencode(target), 4)  # RENAME_EXCL
    else:
        raise ValueError('Atomic firmware export without replacement is unavailable on this platform.')
    if outcome != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def export_bundle_atomic(bundle: FirmwareBundle | dict, destination: str | Path, *,
                         cancelled=lambda: False) -> Path:
    """Export to a NEW folder only. No code, installer or build hook is run."""
    bundle = FirmwareBundle.model_validate(bundle.model_dump() if isinstance(bundle, FirmwareBundle) else bundle)
    target = Path(destination)
    if not target.is_absolute():
        raise ValueError('Select an absolute path for a new firmware export folder.')
    # Do not resolve away a traversal or a junction before checking it.
    if '..' in target.parts or not target.name or target.name[-1] in '. ':
        raise ValueError('Choose a canonical new firmware export folder.')
    validate_relative_path(target.name)
    _reject_reparse(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError('Choose a new folder; an existing firmware project is never overwritten.')
    if not target.parent.is_dir():
        raise ValueError('The firmware export parent directory must already exist.')
    _check_cancelled(cancelled)
    parent = target.parent.resolve(strict=True)
    target = parent / target.name
    stage = Path(tempfile.mkdtemp(prefix='.cad-firmware-', dir=parent))
    try:
        for file in bundle.files:
            _check_cancelled(cancelled)
            path = stage.joinpath(*PurePosixPath(file.path).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(file.content.encode('utf-8')); stream.flush(); os.fsync(stream.fileno())
        manifest = bundle.model_dump_json(indent=2).encode('utf-8')
        with (stage / MANIFEST_NAME).open('xb') as stream:
            stream.write(manifest); stream.flush(); os.fsync(stream.fileno())
        _check_cancelled(cancelled)
        _reject_reparse(target)
        _rename_new_directory(stage, target)
        return target
    finally:
        if stage.exists():
            _reject_reparse(stage)
            if stage.parent.resolve(strict=True) != parent or not stage.name.startswith('.cad-firmware-'):
                raise ValueError('Firmware staging identity changed; recursive cleanup was refused.')
            shutil.rmtree(stage)
