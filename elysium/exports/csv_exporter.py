"""
Background CSV export (LLD section 20.5; docs/IMPLEMENTATION_PLAN.md
section 6.12). Report row-sets can be large enough (company-wide streams/
breaks/audit history) that writing them on the UI thread would freeze the
window -- this mirrors the existing PriceRefreshWorker QThread pattern
(elysium/ui/prices.py) rather than introducing a new concurrency approach.
"""

import csv

from PySide6.QtCore import QThread, Signal


class CsvExportWorker(QThread):
    finished_success = Signal(str)  # destination path
    failed = Signal(str)

    def __init__(self, headers: list[str], rows: list[dict], destination_path: str):
        super().__init__()
        self.headers = headers
        self.rows = rows
        self.destination_path = destination_path

    def run(self):
        try:
            with open(self.destination_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.headers, extrasaction="ignore")
                writer.writeheader()
                for row in self.rows:
                    writer.writerow(row)
        except OSError as e:
            self.failed.emit(str(e))
            return

        self.finished_success.emit(self.destination_path)
