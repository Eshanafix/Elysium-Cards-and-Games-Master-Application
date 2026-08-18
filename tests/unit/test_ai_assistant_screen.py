"""
Regression tests for the admin Ask Elysium screen: it shows the API-key
setup page until a key is configured, switches to the chat page once it is,
and Ask sends the typed question through to the service.
"""

from elysium.models.users import User
from elysium.ui import ai_assistant


def make_screen(qtbot, monkeypatch, configured: bool):
    monkeypatch.setattr(ai_assistant.ai_assistant_service, "is_configured", lambda: configured)

    admin = User(id="a1", username="admin", password_hash="x", roles=["admin"])
    screen = ai_assistant.AiAssistantScreen(admin)
    qtbot.addWidget(screen)
    return screen, admin


def test_shows_setup_page_when_not_configured(qtbot, monkeypatch):
    screen, _ = make_screen(qtbot, monkeypatch, configured=False)

    assert screen.stack.currentIndex() == 0


def test_shows_chat_page_when_already_configured(qtbot, monkeypatch):
    screen, _ = make_screen(qtbot, monkeypatch, configured=True)

    assert screen.stack.currentIndex() == 1


def test_save_api_key_rejects_blank_input(qtbot, monkeypatch):
    screen, _ = make_screen(qtbot, monkeypatch, configured=False)

    called = []
    monkeypatch.setattr(ai_assistant.ai_assistant_service, "configure_api_key", lambda *a, **k: called.append(True))

    screen.api_key_input.setText("")
    screen.save_api_key()

    assert called == []
    assert "enter an api key" in screen.setup_message_label.text().lower()


def test_change_key_button_returns_to_setup_page(qtbot, monkeypatch):
    screen, _ = make_screen(qtbot, monkeypatch, configured=True)

    screen.change_key_button.click()

    assert screen.stack.currentIndex() == 0


def test_ask_appends_question_and_disables_input_while_waiting(qtbot, monkeypatch):
    screen, admin = make_screen(qtbot, monkeypatch, configured=True)
    # ask() starts a real background QThread that calls ai_assistant_service.ask()
    # -- must be mocked here, or this "unit" test makes a real network call to
    # Anthropic (and a real DB read) on any machine that already has the shared
    # key configured, which is exactly the situation this app is designed for.
    monkeypatch.setattr(ai_assistant.ai_assistant_service, "ask", lambda question, asked_by: "mocked answer")

    screen.question_input.setText("Do I profit more on 3 or 4 pack breaks?")
    screen.ask()

    assert "Do I profit more" in screen.conversation_log.toPlainText()
    assert screen.ask_button.isEnabled() is False
    assert screen.question_input.text() == ""

    qtbot.waitUntil(lambda: screen.ask_button.isEnabled(), timeout=5000)


def test_on_ask_finished_reenables_input_and_appends_answer(qtbot, monkeypatch):
    screen, _ = make_screen(qtbot, monkeypatch, configured=True)

    screen.on_ask_finished("4-pack breaks average more profit.")

    assert screen.ask_button.isEnabled() is True
    assert screen.question_input.isEnabled() is True
    assert "4-pack breaks average more profit" in screen.conversation_log.toPlainText()


def test_on_ask_failed_shows_error_and_reenables_input(qtbot, monkeypatch):
    screen, _ = make_screen(qtbot, monkeypatch, configured=True)

    screen.on_ask_failed("The AI assistant hasn't been set up on this account yet.")

    assert screen.ask_button.isEnabled() is True
    assert "hasn't been set up" in screen.conversation_log.toPlainText()
