import os

# Must be set before any PySide6 module loads a platform plugin, so UI tests
# run headlessly in CI / this sandboxed environment without a real display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
