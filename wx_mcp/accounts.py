"""Multi-account manager backed by wechatbot-sdk runtimes."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

from .errors import AccountError
from .runtime import AccountRuntime


class AccountManager:
    def __init__(
        self,
        data_dir: Path | str,
        *,
        base_url: str | None = None,
        bot_agent: str | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.accounts_root = self.data_dir / "accounts"
        self._base_url = base_url
        self._bot_agent = bot_agent
        self._lock = threading.RLock()
        self._runtimes: dict[str, AccountRuntime] = {}

    # ------------------------------------------------------------- helpers

    def _validate_account_id(self, account_id: Any) -> str:
        if not account_id or not str(account_id).strip():
            raise AccountError("account_id is required")
        name = str(account_id).strip()
        if any(c in name for c in '/\\:*?"<>|'):
            raise AccountError("account_id contains invalid characters")
        return name

    def _ensure_runtime(self, account_id: str) -> AccountRuntime:
        with self._lock:
            runtime = self._runtimes.get(account_id)
            if runtime is None:
                runtime = AccountRuntime(
                    account_id,
                    self.accounts_root / account_id / "credentials.json",
                    base_url=self._base_url,
                    bot_agent=self._bot_agent,
                )
                self._runtimes[account_id] = runtime
            return runtime

    # -------------------------------------------------------------- listing

    def list_accounts(self) -> dict[str, Any]:
        ids: set[str] = set(self._runtimes.keys())
        if self.accounts_root.exists():
            for child in self.accounts_root.iterdir():
                if child.is_dir():
                    ids.add(child.name)

        accounts = []
        for account_id in sorted(ids):
            runtime = self._ensure_runtime(account_id)
            accounts.append(runtime.get_status())
        return {"accounts": accounts}

    # --------------------------------------------------------------- login

    def login_account(self, account_id: Any, force: bool = False) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        return self._ensure_runtime(account_id).login(force)

    def get_login_status(self, account_id: Any) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        return self._ensure_runtime(account_id).get_status()

    def submit_verify_code(self, account_id: Any, code: str) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        return self._ensure_runtime(account_id).submit_verify_code(code)

    def set_account_nickname(self, account_id: Any, nickname: Any) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        return self._ensure_runtime(account_id).set_nickname(nickname)

    # ------------------------------------------------------------- logout

    def logout_account(self, account_id: Any) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        return self._ensure_runtime(account_id).logout()

    def remove_account(self, account_id: Any) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        result = self.logout_account(account_id)
        account_dir = self.accounts_root / account_id
        if account_dir.exists():
            shutil.rmtree(account_dir)
        with self._lock:
            self._runtimes.pop(account_id, None)
        return {**result, "account_id": account_id, "status": "removed"}

    # ----------------------------------------------------------- lifecycle

    def start_all(self) -> dict[str, Any]:
        if self.accounts_root.exists():
            for child in self.accounts_root.iterdir():
                if child.is_dir() and (child / "credentials.json").exists():
                    self._ensure_runtime(child.name).resume()
        return self.list_accounts()

    def stop_all(self) -> None:
        runtimes = list(self._runtimes.values())
        for runtime in runtimes:
            runtime.shutdown()

    # ------------------------------------------------------------- actions

    def send_message(
        self, account_id: Any, text: str, to_user_id: Any = None
    ) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        return self._ensure_runtime(account_id).send_text(text, to_user_id or None)

    def send_media(
        self,
        account_id: Any,
        media_type: Any,
        *,
        to_user_id: Any = None,
        file_path: str | None = None,
        data_base64: str | None = None,
        file_name: str | None = None,
        caption: str | None = None,
        media_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        return self._ensure_runtime(account_id).send_media(
            media_type,
            user_id=to_user_id or None,
            file_path=file_path,
            data_base64=data_base64,
            file_name=file_name,
            caption=caption,
            media_ref=media_ref,
        )

    def upload_media(
        self,
        account_id: Any,
        media_type: Any,
        *,
        to_user_id: Any = None,
        file_path: str | None = None,
        data_base64: str | None = None,
        file_name: str | None = None,
    ) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        return self._ensure_runtime(account_id).upload_media(
            media_type,
            user_id=to_user_id or None,
            file_path=file_path,
            data_base64=data_base64,
            file_name=file_name,
        )

    def upload_media_bytes(
        self,
        account_id: Any,
        media_type: Any,
        data: bytes,
        *,
        to_user_id: Any = None,
        file_name: str | None = None,
    ) -> dict[str, Any]:
        account_id = self._validate_account_id(account_id)
        if not isinstance(data, bytes):
            raise AccountError("upload data must be bytes")
        return self._ensure_runtime(account_id).upload_media_bytes(
            media_type,
            data,
            user_id=to_user_id or None,
            file_name=file_name,
        )
