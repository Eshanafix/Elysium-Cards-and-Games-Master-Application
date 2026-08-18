"""
Regression test: unlike every other screen's table, the Reports table's
column set genuinely changes between report types (different columns() per
ReportDefinition), so "only auto-size once, ever" would leave a newly
selected report's columns using leftover widths sized for whatever report
ran before it. Re-running the *same* report (e.g. just changing a filter)
should still preserve a manual resize; switching to a *different* report
should re-auto-size.
"""

from elysium.exports.report_definitions import ReportDefinition
from elysium.ui import reports


class FakeUser:
    id = "admin-1"
    roles = ["admin"]
    streamer_database_name = None


def make_definition(key, columns, rows):
    return ReportDefinition(key=key, label=key, columns=columns, fetch=lambda user, **kwargs: rows)


def make_screen(qtbot, monkeypatch, definitions):
    monkeypatch.setattr(reports, "available_reports", lambda user: definitions)
    monkeypatch.setattr(reports.repo, "list_users", lambda: [])
    monkeypatch.setattr(reports.repo, "list_products", lambda: [])

    screen = reports.ReportsScreen(FakeUser())
    qtbot.addWidget(screen)
    return screen


def test_rerunning_the_same_report_preserves_manual_column_width(qtbot, monkeypatch):
    definition = make_definition("inventory", ["Product", "Packs"], [{"Product": "Foundations Play Booster", "Packs": 10}])
    screen = make_screen(qtbot, monkeypatch, [definition])

    screen.run_report()
    screen.table.setColumnWidth(0, 400)

    screen.run_report()  # same report, e.g. just re-clicking Run

    assert screen.table.columnWidth(0) == 400


def test_switching_to_a_different_report_resizes_its_new_columns(qtbot, monkeypatch):
    report_a = make_definition("inventory", ["Product"], [{"Product": "Foundations Play Booster"}])
    report_b = make_definition(
        "streams", ["Streamer", "Date", "Final Gross", "Profit"],
        [{"Streamer": "streamer1", "Date": "2026-01-01", "Final Gross": "100", "Profit": "40"}],
    )
    screen = make_screen(qtbot, monkeypatch, [report_a, report_b])

    screen.run_report()
    screen.table.setColumnWidth(0, 400)

    # Switch to a different report -- its columns mean something else
    # entirely, so the leftover 400px width shouldn't just carry over.
    idx = screen.report_combo.findData("streams")
    screen.report_combo.setCurrentIndex(idx)
    screen.run_report()

    assert screen.table.columnCount() == 4
    assert screen.table.columnWidth(0) != 400
