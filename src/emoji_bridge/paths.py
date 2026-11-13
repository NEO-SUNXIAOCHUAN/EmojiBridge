"""Code resources are read-only; each pilot account pair gets its own data root."""
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get('EMOJI_BRIDGE_DATA', APP_ROOT)).resolve()


def configure_data_root(path):
    # Launcher calls this before importing any workflow/catalog modules.
    global DATA_ROOT
    DATA_ROOT = Path(path).resolve()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ['EMOJI_BRIDGE_DATA'] = str(DATA_ROOT)
