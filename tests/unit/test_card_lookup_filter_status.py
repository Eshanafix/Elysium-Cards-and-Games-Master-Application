"""
Regression tests: SetFilterDialog's apply/clear handlers previously updated
elysium.selected_set_codes/selected_card_codes and reloaded cards, but
never told the main screen's filter_status_label to refresh -- it stayed
stuck on "Enabled Sets: All Sets" forever, and never mentioned an active
Card Codes filter at all.
"""

from unittest.mock import MagicMock

import pytest

from elysium.ui import card_lookup


@pytest.fixture
def tab(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(card_lookup.db, "get_set_options", lambda db_path: [
        ("dmu", "Dominaria United", 300),
        ("fdn", "Foundations", 350),
    ])
    monkeypatch.setattr(card_lookup.db, "get_last_successful_refresh_at", lambda db_path: None)
    monkeypatch.setattr(card_lookup.db, "search_cards", lambda *a, **k: ([], 0))
    monkeypatch.setattr(card_lookup.paths, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(card_lookup.paths, "get_db_path", lambda: tmp_path / "cards.sqlite")

    widget = card_lookup.CardLookupTab()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_update_filter_status_reflects_selected_sets(tab):
    tab.selected_set_codes = {"dmu"}

    tab.update_filter_status()

    assert "Dominaria United (DMU)" in tab.filter_status_label.text()
    assert tab.clear_filters_button.isVisible()


def test_update_filter_status_reflects_card_codes(tab):
    tab.selected_card_codes = {"123", "124"}

    tab.update_filter_status()

    assert "Card Codes: 123, 124" in tab.filter_status_label.text()
    assert tab.clear_filters_button.isVisible()


def test_update_filter_status_all_sets_when_nothing_selected(tab):
    tab.selected_set_codes = set()
    tab.selected_card_codes = set()

    tab.update_filter_status()

    assert tab.filter_status_label.text() == "Enabled Sets: All Sets"
    assert not tab.clear_filters_button.isVisible()


def test_dialog_apply_filter_updates_main_screen_status_label(tab):
    dialog = card_lookup.SetFilterDialog(parent=tab, selected_set_codes=set(), selected_card_codes=set(), zoom=1.0)
    dialog.get_selected_set_codes = MagicMock(return_value={"dmu"})

    dialog.apply_filter()

    assert tab.selected_set_codes == {"dmu"}
    assert "Dominaria United (DMU)" in tab.filter_status_label.text()


def test_dialog_clear_filter_updates_main_screen_status_label(tab):
    tab.selected_set_codes = {"dmu"}
    tab.update_filter_status()
    dialog = card_lookup.SetFilterDialog(parent=tab, selected_set_codes={"dmu"}, selected_card_codes=set(), zoom=1.0)

    dialog.clear_filter()

    assert tab.selected_set_codes == set()
    assert tab.filter_status_label.text() == "Enabled Sets: All Sets"


def test_dialog_apply_card_code_filter_updates_main_screen_status_label(tab):
    dialog = card_lookup.SetFilterDialog(parent=tab, selected_set_codes=set(), selected_card_codes=set(), zoom=1.0)
    dialog.code_input.setPlainText("123\n124")

    dialog.apply_card_code_filter()

    assert tab.selected_card_codes == {"123", "124"}
    assert "Card Codes" in tab.filter_status_label.text()


def test_clear_all_filters_resets_both_filter_types(tab):
    tab.selected_set_codes = {"dmu"}
    tab.selected_card_codes = {"123"}
    tab.update_filter_status()

    tab.clear_all_filters()

    assert tab.selected_set_codes == set()
    assert tab.selected_card_codes == set()
    assert tab.filter_status_label.text() == "Enabled Sets: All Sets"
    assert not tab.clear_filters_button.isVisible()
