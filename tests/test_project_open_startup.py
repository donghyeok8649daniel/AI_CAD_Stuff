import importlib.util
from pathlib import Path
import pytest


@pytest.fixture
def parse():
    path=Path(__file__).resolve().parents[1]/'native_desktop.py'
    spec=importlib.util.spec_from_file_location('owned_startup_no_dispatch',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.parse_startup_args


def test_data_open_requires_all_three_explicit_arguments(parse):
    with pytest.raises(SystemExit):parse(['--project-open-data-check','out.json'])
    args=parse(['--project-open-data-check','out.json','--project-open-input','input.pcad','--project-open-cache','cache'])
    assert args.project_open_cache==Path('cache')


@pytest.mark.parametrize('extra',[['--open','user.pcad'],['--setup-codex'],['--startup-smoke','other.json']])
def test_data_open_cannot_launch_or_control_an_ordinary_window(parse,extra):
    with pytest.raises(SystemExit):parse(['--project-open-data-check','out.json','--project-open-input','input.pcad','--project-open-cache','cache',*extra])


def test_native_open_smoke_requires_separate_owned_action(parse):
    with pytest.raises(SystemExit):parse(['--project-open-smoke','out.json'])
    args=parse(['--project-open-smoke','out.json','--project-open-smoke-input','input.pcad','--no-restore'])
    assert args.project_open_smoke_input==Path('input.pcad')
    with pytest.raises(SystemExit):parse(['--project-open-smoke','out.json','--project-open-smoke-input','input.pcad','--open','user.pcad'])
