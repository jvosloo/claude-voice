"""Integration tests for Telegram client (daemon/telegram.py)."""

from unittest.mock import patch, MagicMock

from daemon.telegram import TelegramClient


def _make_client():
    return TelegramClient(bot_token="test_token", chat_id="12345")


class TestVerify:

    def test_success(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}

        with patch("daemon.telegram.requests.get", return_value=mock_resp) as mock_get:
            assert client.verify() is True
        mock_get.assert_called_once()

    def test_failure_status_code(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"ok": False}

        with patch("daemon.telegram.requests.get", return_value=mock_resp):
            assert client.verify() is False

    def test_connection_error(self):
        client = _make_client()
        with patch("daemon.telegram.requests.get",
                   side_effect=ConnectionError()):
            assert client.verify() is False


class TestSendMessage:

    def test_success_returns_message_id(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": {"message_id": 42},
        }

        with patch("daemon.telegram.requests.post", return_value=mock_resp):
            assert client.send_message("Hello") == 42

    def test_failure_returns_none(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False}

        with patch("daemon.telegram.requests.post", return_value=mock_resp):
            assert client.send_message("Hello") is None

    def test_includes_reply_markup(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": {"message_id": 1},
        }

        markup = {"inline_keyboard": [[{"text": "Yes", "callback_data": "y"}]]}
        with patch("daemon.telegram.requests.post", return_value=mock_resp) as mock_post:
            client.send_message("Choose", reply_markup=markup)

        payload = mock_post.call_args[1]["json"]
        assert "reply_markup" in payload

    def test_exception_returns_none(self):
        client = _make_client()
        with patch("daemon.telegram.requests.post",
                   side_effect=ConnectionError()):
            assert client.send_message("Hello") is None


class TestDeleteMessage:

    def test_success(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        with patch("daemon.telegram.requests.post", return_value=mock_resp):
            assert client.delete_message(42) is True

    def test_failure(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False}

        with patch("daemon.telegram.requests.post", return_value=mock_resp):
            assert client.delete_message(42) is False

    def test_exception(self):
        client = _make_client()
        with patch("daemon.telegram.requests.post",
                   side_effect=ConnectionError()):
            assert client.delete_message(42) is False


class TestHandleUpdate:

    def test_routes_callback_to_handler(self):
        client = _make_client()
        handler = MagicMock()
        client._callback_handler = handler

        update = {
            "callback_query": {
                "id": "cb1",
                "data": "yes",
                "message": {
                    "message_id": 10,
                    "chat": {"id": 12345},
                },
            }
        }
        client._handle_update(update)
        handler.assert_called_once_with("cb1", "yes", 10)

    def test_routes_message_to_handler(self):
        client = _make_client()
        handler = MagicMock()
        client._message_handler = handler

        update = {
            "message": {
                "text": "hello",
                "chat": {"id": 12345},
            }
        }
        client._handle_update(update)
        handler.assert_called_once_with("hello")

    def test_ignores_wrong_chat_id_callback(self):
        client = _make_client()
        handler = MagicMock()
        client._callback_handler = handler

        update = {
            "callback_query": {
                "id": "cb1",
                "data": "yes",
                "message": {
                    "message_id": 10,
                    "chat": {"id": 99999},  # wrong
                },
            }
        }
        client._handle_update(update)
        handler.assert_not_called()

    def test_ignores_wrong_chat_id_message(self):
        client = _make_client()
        handler = MagicMock()
        client._message_handler = handler

        update = {
            "message": {
                "text": "hello",
                "chat": {"id": 99999},  # wrong
            }
        }
        client._handle_update(update)
        handler.assert_not_called()

    def test_ignores_empty_message_text(self):
        client = _make_client()
        handler = MagicMock()
        client._message_handler = handler

        update = {
            "message": {
                "text": "",
                "chat": {"id": 12345},
            }
        }
        client._handle_update(update)
        handler.assert_not_called()
