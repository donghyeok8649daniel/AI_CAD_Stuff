"""Keep installed user settings across releases without copying credentials."""
import os
from pathlib import Path
import sys

LEGACY_PUBLIC_PROFILE = 'profile-public-3.2.1-project-capacity-20261014'


def default_data_dir(*, environ=None, executable=None, frozen=None):
    env = os.environ if environ is None else environ
    explicit = env.get('CADSTUDIO_DATA_DIR')
    if explicit:
        return Path(explicit)
    is_frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if is_frozen:
        # 3.2.1 used this directory in its installation. Reuse it in place;
        # future versions must not create a new empty profile for each build.
        previous = Path(executable or sys.executable).parent / LEGACY_PUBLIC_PROFILE
        if previous.is_dir() and not previous.is_symlink() and not (
                hasattr(previous, 'is_junction') and previous.is_junction()):
            return previous
    local = env.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(local) / 'PromptCADStudio'
