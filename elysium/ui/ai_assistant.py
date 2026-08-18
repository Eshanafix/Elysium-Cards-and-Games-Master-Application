"""
Admin-only "Ask Elysium" screen (elysium.services.ai_assistant_service).
Shows an inline one-time setup form if no admin has configured the shared
Anthropic API key yet (stored in elysium_master.app_config, so every other
admin's app just picks it up automatically after that -- no per-machine
setup step for anyone else), otherwise a simple question/answer panel.
"""

import html

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elysium.services import ai_assistant_service
from elysium.ui.background import run_worker, safe_callback


class ConfigureKeyWorker(QThread):
    finished_success = Signal()
    failed = Signal(str)

    def __init__(self, api_key: str, configured_by: str):
        super().__init__()
        self.api_key = api_key
        self.configured_by = configured_by

    def run(self):
        try:
            ai_assistant_service.configure_api_key(self.api_key, self.configured_by)
            self.finished_success.emit()
        except Exception as e:
            self.failed.emit(str(e))


class AskWorker(QThread):
    finished_success = Signal(str)
    failed = Signal(str)

    def __init__(self, question: str, asked_by: str):
        super().__init__()
        self.question = question
        self.asked_by = asked_by

    def run(self):
        try:
            answer = ai_assistant_service.ask(self.question, self.asked_by)
            self.finished_success.emit(answer)
        except Exception as e:
            self.failed.emit(str(e))


class AiAssistantScreen(QWidget):
    def __init__(self, user):
        super().__init__()

        self.user = user
        self.configure_worker = None
        self.ask_worker = None

        outer = QVBoxLayout()

        title = QLabel("Ask Elysium")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        outer.addWidget(title)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.stack.addWidget(self._build_setup_page())
        self.stack.addWidget(self._build_chat_page())

        self.setLayout(outer)

        self.reload()

    def reload(self):
        self.stack.setCurrentIndex(1 if ai_assistant_service.is_configured() else 0)

    # --- Setup page (shown until any admin has configured the shared key) ---

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout()

        explanation = QLabel(
            "Ask natural-language questions about your business data -- e.g. \"Do I make "
            "more profit on breaks with 3 or 4 packs?\" -- and get an answer computed from "
            "your real Elysium data. This needs an Anthropic API key, configured once here. "
            "Once set, every other admin's app picks it up automatically -- nobody else has "
            "to do this setup step.\n\n"
            "Only a small set of read-only company-data lookups are ever exposed to the "
            "assistant -- it can't run arbitrary database queries and can't write or change "
            "anything. Note that your questions (and the data needed to answer them) are "
            "sent to Anthropic's API to generate a response, unlike the rest of this app."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        layout.addWidget(QLabel("Anthropic API key:"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("sk-ant-...")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.api_key_input)

        self.setup_progress = QProgressBar()
        self.setup_progress.setRange(0, 0)
        self.setup_progress.setVisible(False)
        layout.addWidget(self.setup_progress)

        self.save_key_button = QPushButton("Save API Key")
        self.save_key_button.clicked.connect(self.save_api_key)
        layout.addWidget(self.save_key_button)

        self.setup_message_label = QLabel()
        self.setup_message_label.setWordWrap(True)
        layout.addWidget(self.setup_message_label)

        layout.addStretch()
        page.setLayout(layout)
        return page

    def save_api_key(self):
        api_key = self.api_key_input.text().strip()

        if not api_key:
            self._show_setup_message("Enter an API key first.", error=True)
            return

        self.save_key_button.setEnabled(False)
        self.setup_progress.setVisible(True)
        self._show_setup_message("Validating key...", error=False)

        self.configure_worker = ConfigureKeyWorker(api_key, self.user.id)
        self.configure_worker.finished_success.connect(safe_callback(self.on_configure_finished))
        self.configure_worker.failed.connect(safe_callback(self.on_configure_failed))
        run_worker(self.configure_worker)

    def on_configure_finished(self):
        self.save_key_button.setEnabled(True)
        self.setup_progress.setVisible(False)
        self.api_key_input.clear()
        self.reload()

    def on_configure_failed(self, error: str):
        self.save_key_button.setEnabled(True)
        self.setup_progress.setVisible(False)
        self._show_setup_message(error, error=True)

    def _show_setup_message(self, text: str, error: bool):
        self.setup_message_label.setStyleSheet("color: #ff6b6b;" if error else "color: #4caf50;")
        self.setup_message_label.setText(text)

    # --- Chat page (shown once the shared key is configured) ---

    def _build_chat_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout()

        self.conversation_log = QTextEdit()
        self.conversation_log.setReadOnly(True)
        layout.addWidget(self.conversation_log, stretch=1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        input_row = QHBoxLayout()
        self.question_input = QLineEdit()
        self.question_input.setPlaceholderText("Ask a question about your business data...")
        self.question_input.returnPressed.connect(self.ask)
        input_row.addWidget(self.question_input, stretch=1)

        self.ask_button = QPushButton("Ask")
        self.ask_button.clicked.connect(self.ask)
        input_row.addWidget(self.ask_button)

        layout.addLayout(input_row)

        change_key_row = QHBoxLayout()
        change_key_row.addStretch()
        self.change_key_button = QPushButton("Change API Key")
        self.change_key_button.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        change_key_row.addWidget(self.change_key_button)
        layout.addLayout(change_key_row)

        page.setLayout(layout)
        return page

    def ask(self):
        question = self.question_input.text().strip()

        if not question:
            return

        self.ask_button.setEnabled(False)
        self.question_input.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.conversation_log.append(f"<b>You:</b> {html.escape(question)}")

        self.ask_worker = AskWorker(question, self.user.id)
        self.ask_worker.finished_success.connect(safe_callback(self.on_ask_finished))
        self.ask_worker.failed.connect(safe_callback(self.on_ask_failed))
        run_worker(self.ask_worker)

        self.question_input.clear()

    def on_ask_finished(self, answer: str):
        self.ask_button.setEnabled(True)
        self.question_input.setEnabled(True)
        self.progress_bar.setVisible(False)
        formatted = html.escape(answer).replace("\n", "<br>")
        self.conversation_log.append(f"<b>Assistant:</b> {formatted}")
        self.conversation_log.append("")

    def on_ask_failed(self, error: str):
        self.ask_button.setEnabled(True)
        self.question_input.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.conversation_log.append(f"<b style='color: #ff6b6b;'>Error:</b> {html.escape(error)}")
        self.conversation_log.append("")
