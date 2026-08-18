"""
Per-machine UI display scale. This is a personal/per-monitor preference,
not shared team data -- stored locally under the same app-data directory
as the local card database (elysium.local_card.paths), never synced via
MongoDB.

Applied via Qt's QT_SCALE_FACTOR environment variable, which the platform
plugin reads exactly once at QApplication startup and layers on top of
whatever per-monitor DPI auto-scaling Qt is already doing -- so bumping
this up does not break scaling correctly across different monitors, it
just multiplies all of it uniformly. There is no supported way to change
this on an already-running QApplication, which is why changing the scale
here always requires an app restart to take effect (elysium/ui/
app_restart.py provides one).

DEFAULT_SCALE was 1.5 (this app's original "make it bigger" default) until
a real crash (STATUS_STACK_BUFFER_OVERRUN, deep inside Qt's own Windows
platform plugin per crash-dump analysis) was confirmed, via live
reproduction, to happen at 150% and stop happening at 100% -- QT_SCALE_FACTOR
sits underneath Qt's native painting code, so pushing it far from 1.0 is
apparently not as safe on this Qt/PySide6 version as the per-user zoom
picker below assumes. Defaulting to 1.0 avoids that path entirely; anyone
who wants things bigger than the baseline size (elysium/main.py's
BASE_FONT_POINT_SIZE, applied via QFont instead) can still raise this from
the Account screen -- it's just no longer where "bigger by default" lives.
"""

import json
from pathlib import Path

from elysium.local_card.paths import get_app_data_dir

DEFAULT_SCALE = 1.0
MIN_SCALE = 0.75
MAX_SCALE = 3.0

# Shown in the Account screen's zoom picker.
SCALE_PRESETS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]


def _settings_path() -> Path:
    return get_app_data_dir() / "ui_settings.json"


def _clamp(scale: float) -> float:
    return max(MIN_SCALE, min(MAX_SCALE, scale))


def get_display_scale() -> float:
    path = _settings_path()

    if not path.exists():
        return DEFAULT_SCALE

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        scale = float(data.get("display_scale", DEFAULT_SCALE))
    except (OSError, ValueError, json.JSONDecodeError):
        return DEFAULT_SCALE

    return _clamp(scale)


def set_display_scale(scale: float) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"display_scale": _clamp(scale)}), encoding="utf-8")
