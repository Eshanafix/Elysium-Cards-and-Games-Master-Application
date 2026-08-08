"""
Regression test: spin boxes used to start at their current value (often 0)
with no text selected, so typing a digit inserted next to it ("5" -> "05")
instead of replacing it. These subclasses select-all on focus so a typed
digit replaces the existing value.
"""

from elysium.ui.numeric_inputs import SelectAllDoubleSpinBox, SelectAllSpinBox


def test_spin_box_focus_in_selects_all_text(qtbot):
    box = SelectAllSpinBox()
    qtbot.addWidget(box)
    box.setValue(0)
    box.show()

    box.setFocus()
    qtbot.waitUntil(lambda: box.lineEdit().selectedText() == "0", timeout=1000)


def test_double_spin_box_focus_in_selects_all_text(qtbot):
    box = SelectAllDoubleSpinBox()
    qtbot.addWidget(box)
    box.setValue(0)
    box.show()

    box.setFocus()
    qtbot.waitUntil(lambda: box.lineEdit().selectedText() == "0.00", timeout=1000)
