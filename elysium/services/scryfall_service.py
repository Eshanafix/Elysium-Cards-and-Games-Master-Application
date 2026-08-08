"""
Local Scryfall card-data refresh, run on a background QThread so the UI
never blocks (LLD 27.1). Ported from the reference project's RefreshWorker
in app.py, now built on the safe-swap rebuild in local_card.db instead of
delete-then-rebuild, so a failed refresh preserves the prior working
database and image cache (LLD 21.6, 26.3).
"""

import logging

from PySide6.QtCore import QThread, Signal

from elysium.local_card import bulk_import, db, image_cache, paths

logger = logging.getLogger(__name__)


class ScryfallRefreshWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished_success = Signal()
    failed = Signal(str)

    def run(self):
        try:
            paths.ensure_app_dirs()

            self.status.emit("Finding latest Scryfall bulk data...")
            self.progress.emit(0)

            bulk_file_path = paths.get_bulk_file_path()

            def download_progress(downloaded, total):
                percent = int((downloaded / total) * 35) if total else 0
                self.progress.emit(percent)

            self.status.emit("Downloading latest card data...")
            bulk_import.download_default_cards(bulk_file_path, progress_callback=download_progress)

            self.status.emit("Loading card data...")
            cards = bulk_import.load_bulk_cards(bulk_file_path)

            self.status.emit("Rebuilding local database...")
            self.progress.emit(40)

            def insert_progress(index, total):
                percent = 40 + int((index / total) * 40) if total else 40
                self.progress.emit(percent)

            db.rebuild_database_safely(
                paths.get_db_path(),
                cards,
                progress_callback=insert_progress,
            )

            self.progress.emit(80)
            self.status.emit("Checking for missing images...")

            def image_progress(completed, total):
                percent = 80 + int((completed / total) * 20) if total else 100
                remaining = total - completed
                self.progress.emit(percent)
                self.status.emit(
                    f"Downloading images... {completed:,}/{total:,} complete ({remaining:,} remaining)"
                )

            image_cache.download_missing_card_images(
                paths.get_db_path(),
                paths.get_cache_dir(),
                progress_callback=image_progress,
            )

            self.progress.emit(100)
            self.status.emit("Card data and image refresh complete.")
            self.finished_success.emit()

        except Exception as e:
            logger.exception("Card data refresh failed")
            self.failed.emit(str(e))
