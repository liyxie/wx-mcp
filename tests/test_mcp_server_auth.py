from wx_mcp.mcp_server import _HttpHandler


def _handler(headers=None, api_key=None):
    handler = _HttpHandler.__new__(_HttpHandler)
    handler.headers = headers or {}
    handler.api_key = api_key
    sent = []

    def send_json(obj, status=200):
        sent.append((status, obj))

    handler._send_json = send_json
    handler.sent = sent
    return handler


def test_provided_api_key_from_x_api_key():
    handler = _handler({"X-API-Key": " secret "})
    assert handler._provided_api_key() == "secret"


def test_provided_api_key_from_authorization_bearer():
    handler = _handler({"Authorization": "Bearer secret"})
    assert handler._provided_api_key() == "secret"


def test_authorized_when_key_not_configured():
    handler = _handler(api_key=None)
    assert handler._authorized() is True


def test_authorized_accepts_matching_key():
    handler = _handler({"X-API-Key": "secret"}, api_key="secret")
    assert handler._authorized() is True


def test_authorized_rejects_wrong_key():
    handler = _handler({"X-API-Key": "wrong"}, api_key="secret")
    assert handler._authorized() is False
    assert handler.sent == [(401, {"error": "unauthorized"})]
