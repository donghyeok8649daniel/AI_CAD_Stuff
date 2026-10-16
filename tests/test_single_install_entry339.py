"""Source/AST only: never starts the CAD app, installer, updater or Windows UI."""
import argparse
import ast
from pathlib import Path

import pytest


ROOT=Path(__file__).resolve().parents[1]
ENTRY=ast.parse((ROOT/'native_desktop.py').read_text(encoding='utf-8'))


def parser():
    function=next(n for n in ENTRY.body if isinstance(n,ast.FunctionDef) and n.name=='parse_startup_args')
    namespace={'argparse':argparse,'Path':Path}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<startup-parser-only>','exec'),namespace)
    return namespace['parse_startup_args']


def test_install_argument_is_exclusive_and_isolated_from_project_or_registration():
    parse=parser();assert parse(['--install-canonical','receipt.json']).install_canonical==Path('receipt.json')
    for extra in [['--open','user.pcad'],['user.pcad'],['--register-cad-files'],['--default-apps'],['--setup-codex']]:
        with pytest.raises(SystemExit) as caught:parse(['--install-canonical','receipt.json',*extra])
        assert caught.value.code==2


def test_install_dispatch_returns_before_Qt_import_and_normal_startup():
    main=next(n for n in ENTRY.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    branch=next(n for n in main.body if isinstance(n,ast.If) and ast.unparse(n.test)=='args.install_canonical')
    assert any(isinstance(n,ast.Return) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='run_install_cli' for n in branch.body)
    qt=[n for n in ast.walk(main) if isinstance(n,ast.ImportFrom) and (n.module or '').startswith('PySide6')]
    assert qt and branch.lineno<min(n.lineno for n in qt)
    registrations=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='register']
    guards=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='require_canonical_executable']
    assert registrations and guards and max(n.lineno for n in guards)<min(n.lineno for n in registrations)


def test_ps_install_and_shortcuts_target_only_canonical_after_verified_receipt():
    install=(ROOT/'scripts/install_native.ps1').read_text(encoding='utf-8')
    shortcut=(ROOT/'create-shortcut.ps1').read_text(encoding='utf-8')
    assert '--install-canonical' in install and 'verified_payload' in install and 'install_dir' in install
    for script in (install,shortcut):
        assert r'Programs\PromptCADStudio' in script and '$cadShortcut.TargetPath = $cadExe' in script
        assert 'GetFolderPath(\'Desktop\')' in script and 'GetFolderPath(\'Programs\')' in script
        assert 'wscript.exe' not in script and 'Start CAD.vbs' not in script
        assert script.index('ExitCode')<script.index('$cadShortcut.TargetPath')
        assert '-WindowStyle Hidden' in script
