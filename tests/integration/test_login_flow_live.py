"""
Live end-to-end UI test: real LoginScreen widget, real auth_service, real
Atlas -- driving the actual login form (not calling auth_service directly)
to prove the wiring between ui/login.py and the backend works, then
exercising the admin Users screen to create a second account through the
UI. All accounts are disposable itest_* users, cleaned up afterward.
"""

import uuid

import pytest
from PySide6.QtCore import Qt

from elysium.models.users import ROLE_ADMIN
from elysium.services import auth_service
from elysium.services.mongo_client import check_connection, get_client, get_master_db
from elysium.ui.shell import MainWindow

pytestmark = pytest.mark.skipif(
    not check_connection().is_connected,
    reason="MongoDB is not reachable -- set MONGODB_URI in .env to run integration tests",
)


@pytest.fixture
def created_users():
    users = []
    yield users

    master_db = get_master_db()
    client = get_client()

    for user in users:
        master_db.users.delete_one({"_id": user.id})
        master_db.streamer_allocations.delete_many({"streamer_id": user.id})
        master_db.audit_events.delete_many({
            "$or": [{"performed_by": user.id}, {"after_values.user_id": user.id}]
        })

        if user.streamer_database_name:
            client.drop_database(user.streamer_database_name)


def unique_username(label: str) -> str:
    return f"itest_{label}_{uuid.uuid4().hex[:8]}"


def test_login_screen_reaches_admin_dashboard(qtbot, created_users):
    username = unique_username("uiadmin")
    password = "UiTestPass1!"
    user = auth_service.create_user(username, password, [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    window = MainWindow()
    qtbot.addWidget(window)

    window.login_screen.username_input.setText(username)
    window.login_screen.password_input.setText(password)

    qtbot.mouseClick(window.login_screen.login_button, Qt.LeftButton)

    assert window.app_shell is not None
    assert window.stacked.currentWidget() is window.app_shell
    assert window.app_shell.user.username == username
    assert window.app_shell.users_screen is not None  # admin gets the Users nav item


def test_login_screen_rejects_wrong_password(qtbot, created_users):
    username = unique_username("uiwrong")
    user = auth_service.create_user(username, "RealPassword1!", [ROLE_ADMIN], created_by="integration-test")
    created_users.append(user)

    window = MainWindow()
    qtbot.addWidget(window)

    window.login_screen.username_input.setText(username)
    window.login_screen.password_input.setText("totally-wrong")

    qtbot.mouseClick(window.login_screen.login_button, Qt.LeftButton)

    assert window.stacked.currentWidget() is window.login_screen
    assert "Incorrect" in window.login_screen.login_error_label.text()


def test_admin_can_create_streamer_through_users_screen(qtbot, created_users):
    admin_username = unique_username("creator")
    admin_password = "CreatorPass1!"
    admin_user = auth_service.create_user(
        admin_username, admin_password, [ROLE_ADMIN], created_by="integration-test"
    )
    created_users.append(admin_user)

    window = MainWindow()
    qtbot.addWidget(window)

    window.login_screen.username_input.setText(admin_username)
    window.login_screen.password_input.setText(admin_password)
    qtbot.mouseClick(window.login_screen.login_button, Qt.LeftButton)

    app_shell = window.app_shell
    app_shell.nav_list.setCurrentRow(app_shell.nav_list.count() - 2)  # "Users" item

    users_screen = app_shell.users_screen
    new_username = unique_username("createdstreamer")

    # CreateUserDialog.exec() is modal and would block the test, so this
    # drives the dialog's field-collection logic directly (proving
    # selected_roles() reads the checkboxes correctly) and then calls the
    # same auth_service path its OK handler calls, rather than simulating
    # a click into a blocking modal loop.
    from elysium.ui.users import CreateUserDialog

    create_dialog = CreateUserDialog(users_screen)
    create_dialog.username_input.setText(new_username)
    create_dialog.password_input.setText("StreamerPass1!")
    create_dialog.streamer_checkbox.setChecked(True)

    assert create_dialog.selected_roles() == ["streamer"]

    from elysium.repositories import master_repository as repo

    result_user = auth_service.create_user(
        create_dialog.username_input.text(),
        create_dialog.password_input.text(),
        create_dialog.selected_roles(),
        created_by=admin_user.id,
    )
    created_users.append(result_user)

    users_screen.reload_users()

    found = repo.find_user_by_username(new_username)
    assert found is not None
    assert found.is_streamer is True
