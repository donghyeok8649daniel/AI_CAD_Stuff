from pathlib import Path

import pytest

from native_desktop import parse_startup_args


@pytest.mark.parametrize("filename", [
    "C:/Users/keidi/Desktop/피로 시험기.pcad",
    "C:/Users/keidi/Desktop/legacy assembly.cad.json",
])
def test_windows_file_argument_and_explicit_open_choose_same_project(filename):
    assert parse_startup_args([filename]).open == Path(filename)
    assert parse_startup_args(["--open", filename]).open == Path(filename)


def test_windows_file_argument_can_follow_startup_options():
    args = parse_startup_args(["--no-restore", "한글 파일.pcad", "--renderer", "software"])
    assert args.open == Path("한글 파일.pcad")
    assert args.no_restore and args.renderer == "software"


def test_empty_startup_has_no_project_to_open():
    assert parse_startup_args([]).open is None


def test_motion_precision_smoke_has_an_isolated_synthetic_startup():
    args=parse_startup_args(['--motion-precision-smoke','owned.json','--no-restore','--renderer','software'])
    assert args.motion_precision_smoke==Path('owned.json') and args.open is None


@pytest.mark.parametrize('extra',[['user.pcad'],['--open','user.pcad'],['--setup-codex'],['--g474-pin-smoke','other.json']])
def test_motion_precision_smoke_cannot_open_or_modify_a_user_project(extra):
    with pytest.raises(SystemExit) as exc:parse_startup_args(['--motion-precision-smoke','owned.json',*extra])
    assert exc.value.code==2


@pytest.mark.parametrize("argv", [
    ["one.pcad", "two.pcad"],
    ["--open", "one.pcad", "two.pcad"],
    ["--open", "same.pcad", "same.pcad"],
    ["--unknown-startup-option"],
])
def test_ambiguous_or_unknown_arguments_are_not_silently_ignored(argv):
    with pytest.raises(SystemExit) as exc:
        parse_startup_args(argv)
    assert exc.value.code == 2
