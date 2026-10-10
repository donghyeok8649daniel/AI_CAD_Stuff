from pathlib import Path

import pytest

from native_desktop import parse_startup_args


def test_print_batch_smoke_uses_only_owned_profile():
    args = parse_startup_args(['--print-batch-smoke', 'owned.json', '--renderer', 'software', '--no-restore'])
    assert args.print_batch_smoke == Path('owned.json')
    assert args.open is None
    assert args.no_restore


@pytest.mark.parametrize('extra', [['--open', 'user.pcad'], ['user.pcad'], ['--setup-codex'],
                                  ['--motion-precision-smoke', 'other.json']])
def test_print_batch_smoke_rejects_other_actions(extra):
    with pytest.raises(SystemExit) as error:
        parse_startup_args(['--print-batch-smoke', 'owned.json', *extra])
    assert error.value.code == 2
