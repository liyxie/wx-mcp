"""Per-account runtime built on top of wechatbot-sdk.

Each account gets its own :class:`WeChatBot` instance, its own asyncio event
loop (running in a daemon thread) and its own credential path, so multiple
WeChat accounts stay fully isolated.

Login and media upload use the SDK's high-level ``WeChatBot`` API. Long-polling
and message sending go through the SDK's ``ILinkApi`` so wx-mcp can also
implement the "push to the bound account without a prior context_token" flow
(the SDK's ``WeChatBot.send`` requires a cached context_token).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import threading
from pathlib import Path
from typing import Any

from wechatbot import MediaType, WeChatBot
from wechatbot.protocol import ILinkApi, MessageItemType

from .errors import AccountError, ApiError, AuthError, MediaError, NoContextError

MAX_MSG_LEN = 4000

_MEDIA_BY_NAME = {"image": MediaType.IMAGE, "video": MediaType.VIDEO, "file": MediaType.FILE, "voice": MediaType.VOICE}
_MEDIA_NAMES = {MediaType.IMAGE: "image", MediaType.VIDEO: "video", MediaType.FILE: "file", MediaType.VOICE: "voice"}


def normalize_media_type(value: Any) -> MediaType:
    if isinstance(value, MediaType):
        return value
    if isinstance(value, int):
        if value in _MEDIA_NAMES:
            return MediaType(value)
        raise MediaError(f"Unsupported media_type: {value}")
    if isinstance(value, str):
        key = value.strip().lower()
        if key in _MEDIA_BY_NAME:
            return _MEDIA_BY_NAME[key]
        if key.isdigit() and int(key) in _MEDIA_NAMES:
            return MediaType(int(key))
    raise MediaError(f"Unsupported media_type: {value!r}")


def media_type_name(value: MediaType | int) -> str:
    return _MEDIA_NAMES.get(MediaType(int(value)), "unknown")


def resolve_media_data(
    *,
    data: bytes | None = None,
    file_path: str | None = None,
    data_base64: str | None = None,
) -> bytes:
    provided = [x is not None and x != "" for x in (data, file_path, data_base64)]
    if sum(provided) != 1:
        raise MediaError("Provide exactly one of data, file_path or data_base64")
    if data is not None:
        return bytes(data)
    if file_path is not None:
        return Path(file_path).read_bytes()
    if data_base64 is not None:
        try:
            return base64.b64decode(data_base64)
        except Exception as e:  # pragma: no cover - defensive
            raise MediaError(f"Invalid base64 data: {e}") from e
    raise MediaError("No media data provided")


def infer_file_name(file_path: str | None) -> str:
    if file_path:
        return Path(file_path).name or "file.bin"
    return "file.bin"


def chunk_text(text: str, limit: int = MAX_MSG_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = -1
        idx = window.rfind("\n\n")
        if idx > limit * 3 // 10:
            cut = idx + 2
        if cut == -1:
            idx = window.rfind("\n")
            if idx > limit * 3 // 10:
                cut = idx + 1
        if cut == -1:
            idx = window.rfind(" ")
            if idx > limit * 3 // 10:
                cut = idx + 1
        if cut == -1:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    return chunks or [""]


def _media_dict(cdn_media: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "encrypt_query_param": cdn_media.encrypt_query_param,
        "aes_key": cdn_media.aes_key,
    }
    if cdn_media.encrypt_type is not None:
        data["encrypt_type"] = cdn_media.encrypt_type
    return data


def _media_item(
    media: dict[str, Any],
    media_type: MediaType,
    *,
    encrypted_size: int = 0,
    raw_size: int = 0,
    file_name: str = "file.bin",
) -> dict[str, Any]:
    if media_type == MediaType.IMAGE:
        return {
            "type": int(MessageItemType.IMAGE),
            "image_item": {"media": media, "mid_size": encrypted_size},
        }
    if media_type == MediaType.VIDEO:
        return {
            "type": int(MessageItemType.VIDEO),
            "video_item": {"media": media, "video_size": encrypted_size},
        }
    if media_type == MediaType.FILE:
        return {
            "type": int(MessageItemType.FILE),
            "file_item": {
                "media": media,
                "file_name": file_name,
                "len": str(raw_size),
            },
        }
    raise MediaError(f"Cannot build message item for media_type {media_type!r}")


class AccountRuntime:
    """Owns one WeChat account: event loop, WeChatBot, status and actions."""

    def __init__(
        self,
        account_id: str,
        cred_path: Path,
        *,
        base_url: str | None = None,
        bot_agent: str | None = None,
    ) -> None:
        self.account_id = account_id
        self.cred_path = Path(cred_path)
        self._base_url = base_url
        self._bot_agent = bot_agent

        self.api = ILinkApi(bot_agent=bot_agent)
        self.bot = WeChatBot(
            base_url=base_url,
            cred_path=str(self.cred_path),
            bot_agent=bot_agent,
            on_qr_url=self._on_qr_url,
            on_scanned=self._on_scanned,
            on_expired=self._on_expired,
            on_error=self._on_error,
            on_verify_code=self._on_verify_code,
        )

        self.loop = asyncio.new_event_loop()
        self._thread: threading.Thread | None = None
        self._poll_task: asyncio.Task | None = None
        self._stop_event = threading.Event()

        self.online = False
        self.status = "stopped"
        self.qr_url = ""
        self.qr_id = ""
        self.last_error = ""
        self._qr_event = threading.Event()
        self._verify_event = threading.Event()
        self._verify_code: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ lifecycle

    def ensure_loop(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._loop_main,
                name=f"wx-mcp-{self.account_id}",
                daemon=True,
            )
            self._thread.start()

    def _loop_main(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, coro: Any, timeout: float = 60.0) -> Any:
        self.ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=timeout)

    def has_credentials(self) -> bool:
        return self.bot.get_credentials() is not None or self.cred_path.exists()

    # --------------------------------------------------------------- status

    def _on_qr_url(self, url: str) -> None:
        with self._lock:
            self.qr_url = url
            self.status = "waiting"
        self._qr_event.set()

    def _on_scanned(self) -> None:
        with self._lock:
            self.status = "scaned"

    def _on_expired(self) -> None:
        with self._lock:
            self.status = "expired"

    def _on_error(self, error: Exception) -> None:
        with self._lock:
            self.last_error = str(error)
            if self.status not in ("confirmed",):
                self.status = "error"

    def _on_verify_code(self, is_retry: bool) -> str:
        with self._lock:
            self.status = "need_verifycode"
        self._verify_code = None
        self._verify_event.clear()
        if not self._verify_event.wait(timeout=300):
            raise AuthError("Pairing code was not submitted within 5 minutes")
        return self._verify_code or ""

    def get_status(self) -> dict[str, Any]:
        creds = self.bot.get_credentials()
        return {
            "account_id": self.account_id,
            "status": self.status,
            "online": self.online,
            "qr_url": self.qr_url,
            "qr_id": self.qr_id,
            "error": self.last_error,
            "user_id": creds.user_id if creds else "",
            "bot_id": creds.account_id if creds else "",
            "context_tokens": len(self.bot._context_tokens),
        }

    # ---------------------------------------------------------------- login

    def resume(self) -> None:
        """Resume a persisted account without re-scanning (non-blocking)."""
        if not self.cred_path.exists():
            return
        self.ensure_loop()
        asyncio.run_coroutine_threadsafe(self._ensure_poll(), self.loop)

    def login(self, force: bool = False) -> dict[str, Any]:
        if not force and self.cred_path.exists():
            self.ensure_loop()
            asyncio.run_coroutine_threadsafe(self._ensure_poll(), self.loop).result(timeout=10)
            creds = self.bot.get_credentials()
            return {
                "account_id": self.account_id,
                "status": "confirmed",
                "already_logged_in": True,
                "user_id": creds.user_id if creds else "",
                "bot_id": creds.account_id if creds else "",
                "online": self.online,
            }

        self._qr_event.clear()
        with self._lock:
            self.qr_url = ""
            self.qr_id = ""
            self.last_error = ""
            self.status = "starting"

        self.ensure_loop()
        asyncio.run_coroutine_threadsafe(self._async_login(force), self.loop)
        self._qr_event.wait(timeout=30)
        return self.get_status()

    async def _async_login(self, force: bool) -> None:
        try:
            if force:
                await self._stop_poll()
            await self.bot.login(force=force)
            with self._lock:
                self.status = "confirmed"
            self._start_poll()
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self.last_error = str(e)
                self.status = "error"
        finally:
            self._qr_event.set()

    async def _stop_poll(self) -> None:
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await asyncio.wait_for(self._poll_task, timeout=5)
            except Exception:  # noqa: BLE001
                pass

    def submit_verify_code(self, code: str) -> dict[str, Any]:
        if self.status != "need_verifycode":
            raise AccountError(
                f"No pending pairing-code request for account '{self.account_id}'"
            )
        self._verify_code = code.strip()
        self._verify_event.set()
        return {"account_id": self.account_id, "status": "code_submitted"}

    # ------------------------------------------------------------- keepalive

    async def _ensure_poll(self) -> None:
        creds = self.bot.get_credentials()
        if not creds:
            creds = await self.bot.login()
        with self._lock:
            self.status = "confirmed"
        self._start_poll()

    def _start_poll(self) -> None:
        if self._poll_task is None or self._poll_task.done():
            self._stop_event.clear()
            self._poll_task = self.loop.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        self.online = True
        try:
            creds = self.bot.get_credentials()
            try:
                await self.api.notify_start(creds.base_url, creds.token)
            except Exception:  # noqa: BLE001
                pass

            cursor = ""
            backoff = 1.0
            while not self._stop_event.is_set():
                creds = self.bot.get_credentials()
                if not creds:
                    break
                try:
                    updates = await self.api.get_updates(creds.base_url, creds.token, cursor)
                    buf = updates.get("get_updates_buf")
                    if buf:
                        cursor = buf
                    for raw in updates.get("msgs") or []:
                        self.bot._remember_context(raw)
                    self.online = True
                    backoff = 1.0
                except ApiError as e:
                    if e.is_session_expired:
                        with self._lock:
                            self.status = "session_expired"
                        self.online = False
                        self.bot._credentials = None
                        self.cred_path.unlink(missing_ok=True)
                        self.bot._context_tokens.clear()
                        break
                    with self._lock:
                        self.last_error = str(e)
                except Exception as e:  # noqa: BLE001
                    with self._lock:
                        self.last_error = str(e)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)
        finally:
            self.online = False
            creds = self.bot.get_credentials()
            if creds:
                try:
                    await self.api.notify_stop(creds.base_url, creds.token)
                except Exception:  # noqa: BLE001
                    pass
            self._poll_task = None

    def logout(self) -> dict[str, Any]:
        self.ensure_loop()
        asyncio.run_coroutine_threadsafe(self._async_logout(), self.loop).result(timeout=10)
        return {"account_id": self.account_id, "status": "logged_out"}

    async def _async_logout(self) -> None:
        self._stop_event.set()
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await asyncio.wait_for(self._poll_task, timeout=5)
            except Exception:  # noqa: BLE001
                pass
        creds = self.bot.get_credentials()
        if creds:
            try:
                await self.api.notify_stop(creds.base_url, creds.token)
            except Exception:  # noqa: BLE001
                pass
        self.bot._credentials = None
        self.bot._context_tokens.clear()
        self.cred_path.unlink(missing_ok=True)
        self.online = False
        with self._lock:
            self.status = "logged_out"
            self.qr_url = ""
            self.last_error = ""

    def shutdown(self) -> None:
        self._stop_event.set()
        try:
            if self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self._async_shutdown(), self.loop)
        except Exception:  # noqa: BLE001
            pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)

    async def _async_shutdown(self) -> None:
        self._stop_event.set()
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await asyncio.wait_for(self._poll_task, timeout=5)
            except Exception:  # noqa: BLE001
                pass
        self.online = False

    # ------------------------------------------------------------- messaging

    def _require_creds(self) -> Any:
        creds = self.bot.get_credentials()
        if not creds:
            raise AccountError(f"Account '{self.account_id}' is not logged in")
        return creds

    def _resolve_target(self, user_id: str | None) -> tuple[str, Any]:
        creds = self._require_creds()
        target = (user_id or "").strip() or creds.user_id
        if not target:
            raise NoContextError("")
        return target, creds

    def send_text(self, text: str, user_id: str | None = None) -> dict[str, Any]:
        return self.call(self._async_send_text(text, user_id))

    async def _async_send_text(self, text: str, user_id: str | None) -> dict[str, Any]:
        if not text or not text.strip():
            raise ValueError("Message text cannot be empty")
        target, creds = self._resolve_target(user_id)
        context_token = self.bot._context_tokens.get(target)
        mode = "reply" if context_token else "push"
        if not context_token and target != creds.user_id:
            raise NoContextError(target)

        chunks = chunk_text(text.strip())
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                chunk = f"[{i + 1}/{len(chunks)}]\n{chunk}"
            msg = self.api.build_text_message(target, context_token or "", chunk)
            if not context_token:
                msg["from_user_id"] = creds.account_id
                msg.pop("context_token", None)
            await self.api.send_message(creds.base_url, creds.token, msg)
        return {
            "to_user_id": target,
            "chunks": len(chunks),
            "chars": len(text),
            "mode": mode,
        }

    def send_media(
        self,
        media_type: Any,
        *,
        user_id: str | None = None,
        file_path: str | None = None,
        data_base64: str | None = None,
        file_name: str | None = None,
        caption: str | None = None,
        media_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.call(
            self._async_send_media(
                media_type,
                user_id=user_id,
                file_path=file_path,
                data_base64=data_base64,
                file_name=file_name,
                caption=caption,
                media_ref=media_ref,
            )
        )

    async def _async_send_media(
        self,
        media_type: Any,
        *,
        user_id: str | None,
        file_path: str | None,
        data_base64: str | None,
        file_name: str | None,
        caption: str | None,
        media_ref: dict[str, Any] | None,
    ) -> dict[str, Any]:
        mt = normalize_media_type(media_type)
        target, creds = self._resolve_target(user_id)
        context_token = self.bot._context_tokens.get(target)
        mode = "reply" if context_token else "push"
        if not context_token and target != creds.user_id:
            raise NoContextError(target)

        if media_ref:
            if not media_ref.get("encrypt_query_param") or not media_ref.get("aes_key"):
                raise MediaError("media_ref must contain encrypt_query_param and aes_key")
            media = {
                "encrypt_query_param": media_ref["encrypt_query_param"],
                "aes_key": media_ref["aes_key"],
            }
            if media_ref.get("encrypt_type") is not None:
                media["encrypt_type"] = media_ref["encrypt_type"]
            encrypted_size = int(media_ref.get("encrypted_file_size") or 0)
            raw_size = int(media_ref.get("raw_size") or 0)
        else:
            data = resolve_media_data(file_path=file_path, data_base64=data_base64)
            upload = await self.bot.upload(data, target, int(mt))
            media = _media_dict(upload.media)
            encrypted_size = upload.encrypted_file_size
            raw_size = len(data)
            file_name = file_name or infer_file_name(file_path)

        items: list[dict[str, Any]] = []
        if caption:
            items.append({"type": int(MessageItemType.TEXT), "text_item": {"text": caption}})
        items.append(
            _media_item(
                media,
                mt,
                encrypted_size=encrypted_size,
                raw_size=raw_size,
                file_name=file_name or "file.bin",
            )
        )

        msg = self.api.build_media_message(target, context_token or "", items)
        if not context_token:
            msg["from_user_id"] = creds.account_id
            msg.pop("context_token", None)
        await self.api.send_message(creds.base_url, creds.token, msg)
        return {
            "to_user_id": target,
            "media_type": media_type_name(mt),
            "file_name": file_name or "",
            "mode": mode,
        }

    def upload_media(
        self,
        media_type: Any,
        *,
        user_id: str | None = None,
        file_path: str | None = None,
        data_base64: str | None = None,
        file_name: str | None = None,
    ) -> dict[str, Any]:
        return self.call(
            self._async_upload_media(
                media_type,
                user_id=user_id,
                file_path=file_path,
                data_base64=data_base64,
                file_name=file_name,
            )
        )

    async def _async_upload_media(
        self,
        media_type: Any,
        *,
        user_id: str | None,
        file_path: str | None,
        data_base64: str | None,
        file_name: str | None,
    ) -> dict[str, Any]:
        mt = normalize_media_type(media_type)
        target, _creds = self._resolve_target(user_id)
        data = resolve_media_data(file_path=file_path, data_base64=data_base64)
        upload = await self.bot.upload(data, target, int(mt))
        return {
            "media": _media_dict(upload.media),
            "media_type": media_type_name(mt),
            "encrypted_file_size": upload.encrypted_file_size,
            "raw_size": len(data),
            "md5": hashlib.md5(data).hexdigest(),
            "file_name": file_name or infer_file_name(file_path),
        }
