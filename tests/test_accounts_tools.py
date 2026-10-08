import pytest

from wx_mcp.accounts import AccountManager
from wx_mcp.errors import AccountError
from wx_mcp.tools import ToolRegistry


def test_empty_manager(tmp_path):
    manager = AccountManager(tmp_path / "data")
    assert manager.list_accounts() == {"accounts": []}
    assert manager.get_login_status("missing")["status"] == "stopped"


def test_logout_and_remove_idempotent(tmp_path):
    manager = AccountManager(tmp_path / "data")
    assert manager.logout_account("a")["status"] == "logged_out"
    assert manager.remove_account("a")["status"] == "removed"


def test_send_without_login_raises(tmp_path):
    manager = AccountManager(tmp_path / "data")
    with pytest.raises(AccountError):
        manager.send_message("a", "hello")


def test_submit_verify_code_requires_pending(tmp_path):
    manager = AccountManager(tmp_path / "data")
    with pytest.raises(AccountError):
        manager.submit_verify_code("a", "123")


def test_set_account_nickname_persists(tmp_path):
    data_dir = tmp_path / "data"
    manager = AccountManager(data_dir)
    result = manager.set_account_nickname("work", "  工作号  ")
    assert result == {"account_id": "work", "nickname": "工作号"}

    accounts = manager.list_accounts()["accounts"]
    assert accounts[0]["account_id"] == "work"
    assert accounts[0]["nickname"] == "工作号"

    reloaded = AccountManager(data_dir)
    accounts = reloaded.list_accounts()["accounts"]
    assert accounts[0]["nickname"] == "工作号"


def test_set_account_nickname_rejects_too_long(tmp_path):
    manager = AccountManager(tmp_path / "data")
    with pytest.raises(AccountError):
        manager.set_account_nickname("work", "x" * 65)


def test_tool_registry_lists_and_calls(tmp_path):
    manager = AccountManager(tmp_path / "data")
    registry = ToolRegistry(manager)
    names = {t["name"] for t in registry.list_tools()}
    assert {
        "list_accounts",
        "login_account",
        "get_login_status",
        "set_account_nickname",
        "submit_verify_code",
        "logout_account",
        "send_message",
        "send_media",
        "upload_media",
    } <= names
    assert registry.call("list_accounts", {}) == {"accounts": []}
    assert registry.call(
        "set_account_nickname", {"account_id": "work", "nickname": "工作号"}
    ) == {"account_id": "work", "nickname": "工作号"}
