import base64
import json

import pytest
from wechatbot import MediaType

from wx_mcp.errors import ApiError, ContextRequiredError, MediaError
from wx_mcp.runtime import (
    _is_prepare_failed,
    _media_item,
    chunk_text,
    media_type_name,
    normalize_media_type,
    resolve_media_data,
)


def test_normalize_media_type():
    assert normalize_media_type("image") == MediaType.IMAGE
    assert normalize_media_type("FILE") == MediaType.FILE
    assert normalize_media_type("2") == MediaType.VIDEO
    assert normalize_media_type(MediaType.VIDEO) == MediaType.VIDEO
    assert normalize_media_type(3) == MediaType.FILE
    with pytest.raises(MediaError):
        normalize_media_type("sticker")


def test_media_type_name():
    assert media_type_name(MediaType.IMAGE) == "image"
    assert media_type_name(3) == "file"


def test_resolve_media_data_exactly_one(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"abc")
    assert resolve_media_data(file_path=str(p)) == b"abc"
    assert resolve_media_data(data_base64=base64.b64encode(b"xyz").decode()) == b"xyz"
    with pytest.raises(MediaError):
        resolve_media_data()
    with pytest.raises(MediaError):
        resolve_media_data(data=b"a", data_base64="YQ==")


def test_chunk_text():
    assert chunk_text("hello", 2000) == ["hello"]
    text = "A" * 5000
    chunks = chunk_text(text, 2000)
    assert "".join(chunks) == text
    assert all(len(c) <= 2000 for c in chunks)


def test_media_item_is_json_serializable():
    media = {"encrypt_query_param": "p", "aes_key": "k", "encrypt_type": 1}
    item = _media_item(
        media,
        MediaType.FILE,
        encrypted_size=16,
        raw_size=10,
        file_name="x.pdf",
    )
    json.dumps(item)
    assert item["file_item"]["file_name"] == "x.pdf"


def test_is_prepare_failed_detects_missing_context():
    assert _is_prepare_failed(ApiError("prepare failed"))
    assert _is_prepare_failed(ApiError("x", payload={"errmsg": "prepare failed"}))
    assert not _is_prepare_failed(ApiError("other error"))


def test_context_required_error_is_actionable():
    error = ContextRequiredError("alice@im.wechat")
    assert "context_token" in str(error)
    assert "inbound message" in str(error)
