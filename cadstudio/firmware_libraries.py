"""Read bounded local source snapshots without extracting ZIPs or importing code."""
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from .firmware_bundle import (FirmwareFile, FirmwareLibrary, MAX_FILE_BYTES,
    SOURCE_SUFFIXES, _digest, _reject_reparse, validate_relative_path)

MAX_LIBRARY_FILES = 128
MAX_LIBRARY_BYTES = 2 * 1024 * 1024
MAX_SCAN_FILES = 256
MAX_ZIP_BYTES = 32 * 1024 * 1024
_SKIP_DIRECTORIES = {'.git', '.hg', '.svn', '__pycache__', 'node_modules', '.venv', 'venv', 'build', 'dist'}


def library_id(name):
    result = re.sub(r'[^a-z0-9_-]+', '-', name.casefold()).strip('-_')[:55]
    result = result if result and result[0].isalpha() else 'lib-' + (result or 'source')
    try:
        validate_relative_path('libraries/' + result)
    except ValueError:
        result = 'lib-' + result
    return result


def pinned_dependency(name, version, ecosystem, *, module_names=()):
    return FirmwareLibrary(id=library_id(name), name=name, version=version,
        ecosystem=ecosystem, origin='external', module_names=list(module_names))


def _snapshot(entries, *, name, version, ecosystem, origin, cancelled):
    files = []; omitted = []; total = 0
    for path, size, read in entries:
        if cancelled():
            raise InterruptedError('Library import cancelled; no draft was changed.')
        validate_relative_path(path)
        validate_relative_path('libraries/' + library_id(name) + '/' + path)
        suffix = PurePosixPath(path).suffix.casefold()
        role = ('source' if suffix in SOURCE_SUFFIXES else 'configuration' if suffix == '.json'
                else 'documentation' if suffix in {'.txt', '.md'} or PurePosixPath(path).name.casefold() in
                {'license', 'license-mit', 'license-apache', 'copying', 'notice', 'readme', 'library.properties'} else None)
        if role is None or any(part.casefold() in _SKIP_DIRECTORIES for part in PurePosixPath(path).parts):
            omitted.append(path); continue
        if size > MAX_FILE_BYTES:
            raise ValueError('Library text file exceeds 256 KiB: ' + path)
        if len(files) >= MAX_LIBRARY_FILES or total + size > MAX_LIBRARY_BYTES:
            raise ValueError('Library snapshot exceeds 128 files or 2 MiB; select a smaller source directory.')
        raw = read()
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError('Library file grew beyond 256 KiB while importing: ' + path)
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            omitted.append(path); continue
        if '\x00' in content:
            omitted.append(path); continue
        encoded = content.encode('utf-8'); total += len(encoded)
        files.append(FirmwareFile(path=path, content=content, role=role, sha256=sha256(encoded).hexdigest()))
    if not files:
        raise ValueError('No supported UTF-8 source files were found in this library.')
    search = ['']
    search += [path for path in ('src', 'include') if any(file.path.startswith(path + '/') for file in files)]
    return FirmwareLibrary(id=library_id(name), name=name, version=version, ecosystem=ecosystem,
        origin=origin, files=files, include_paths=search, omitted_files=omitted,
        source_sha256=_digest([(file.path, file.sha256) for file in sorted(files, key=lambda item: item.path)]))


def import_library_directory(path, *, name, version, ecosystem, cancelled=lambda: False):
    root = Path(path).absolute(); _reject_reparse(root)
    if not root.is_dir():
        raise ValueError('Select an existing library source directory.')
    entries = []; pending = [root]; count = 0
    while pending:
        directory = pending.pop()
        for item in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
            if cancelled():
                raise InterruptedError('Library import cancelled; no draft was changed.')
            _reject_reparse(item)
            relative = item.relative_to(root).as_posix()
            if item.is_dir() and item.name.casefold() in _SKIP_DIRECTORIES:
                continue
            validate_relative_path(relative)
            count += 1
            if count > MAX_SCAN_FILES:
                raise ValueError('Library import scans at most 256 entries; select its source subdirectory.')
            if item.is_dir():
                pending.append(item)
            elif item.is_file():
                def read(item=item):
                    _reject_reparse(item)
                    with item.open('rb') as stream:
                        return stream.read(MAX_FILE_BYTES + 1)
                entries.append((relative, item.stat().st_size, read))
            else:
                raise ValueError('Library imports require ordinary files and directories.')
    return _snapshot(sorted(entries), name=name, version=version, ecosystem=ecosystem,
        origin='directory', cancelled=cancelled)


def import_library_zip(path, *, name, version, ecosystem, cancelled=lambda: False):
    source = Path(path).absolute(); _reject_reparse(source)
    if not source.is_file() or source.stat().st_size > MAX_ZIP_BYTES:
        raise ValueError('Select an ordinary ZIP archive within 32 MiB.')
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_SCAN_FILES:
            raise ValueError('Library ZIP contains more than 256 entries; select a smaller source archive.')
        names = set(); files = []
        for info in infos:
            if info.orig_filename != info.filename:
                raise ValueError('ZIP filenames must use canonical forward-slash paths without NULs.')
            path = info.filename.rstrip('/') if info.is_dir() else info.filename
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                raise ValueError('Library ZIP cannot contain symbolic links or special files.')
            if any(part.casefold() in _SKIP_DIRECTORIES for part in PurePosixPath(path).parts):
                # Still reject traversal/absolute archive names, including ignored entries.
                if path.startswith('/') or '..' in path.split('/') or '\\' in path or ':' in path:
                    raise ValueError('Unsafe library archive path.')
                continue
            validate_relative_path(path)
            if path.casefold() in names:
                raise ValueError('ZIP filenames have duplicate or case-insensitive aliases.')
            names.add(path.casefold())
            if info.flag_bits & 1:
                raise ValueError('Encrypted library archives are not supported.')
            if not info.is_dir():
                files.append(info)
        # Common GitHub release ZIPs wrap all source in one directory.
        roots = {info.filename.split('/')[0] for info in files}
        wrapper = next(iter(roots)) + '/' if len(roots) == 1 and all('/' in info.filename for info in files) else ''
        entries = []
        for info in files:
            def read(info=info):
                with archive.open(info, 'r') as stream:
                    return stream.read(MAX_FILE_BYTES + 1)
            entries.append((info.filename[len(wrapper):], info.file_size, read))
        return _snapshot(sorted(entries), name=name, version=version, ecosystem=ecosystem,
            origin='zip', cancelled=cancelled)
