"""Integration tests for Telegram client (daemon/telegram.py)."""

import requests
from unittest.mock import patch, MagicMock, call

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
            ok, reason = client.verify()
            assert ok is True
            assert reason == ""
        mock_get.assert_called_once()

    def test_failure_status_code(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"ok": False}

        with patch("daemon.telegram.requests.get", return_value=mock_resp):
            ok, reason = client.verify()
            assert ok is False
            assert "invalid bot token" in reason

    def test_server_error(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"ok": False}

        with patch("daemon.telegram.requests.get", return_value=mock_resp):
            ok, reason = client.verify()
            assert ok is False
            assert "500" in reason

    def test_connection_error(self):
        client = _make_client()
        with patch("daemon.telegram.requests.get",
                   side_effect=requests.ConnectionError()):
            ok, reason = client.verify()
            assert ok is False
            assert "cannot reach" in reason


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


def _setup_poll_session(client, fake_get):
    """Set up a mock poll session for _poll_loop tests."""
    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=fake_get)
    client._poll_session = mock_session
    client._polling = True
    return mock_session


class TestPollLoopResilience:

    def test_retries_on_api_error(self):
        """Polling continues after API returns {"ok": false}."""
        client = _make_client()
        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count <= 3:
                resp.json.return_value = {"ok": False}
            else:
                # Stop the loop after proving it survived errors
                client._polling = False
                resp.json.return_value = {"ok": True, "result": []}
            return resp

        _setup_poll_session(client, fake_get)
        with patch("daemon.telegram.time.sleep"):
            client._poll_loop()

        # Survived 3 API errors and reached the 4th call
        assert call_count == 4

    def test_retries_on_exception(self):
        """Polling continues after connection errors."""
        client = _make_client()
        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 6:
                raise ConnectionError("DNS resolution failed")
            # Stop after proving it survived 6 consecutive exceptions
            client._polling = False
            resp = MagicMock()
            resp.json.return_value = {"ok": True, "result": []}
            return resp

        _setup_poll_session(client, fake_get)
        with patch("daemon.telegram.time.sleep"):
            client._poll_loop()

        assert call_count == 7

    def test_stops_only_on_flag(self):
        """Loop only exits when self._polling is set to False."""
        client = _make_client()
        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                client._polling = False
            resp = MagicMock()
            resp.json.return_value = {"ok": True, "result": []}
            return resp

        _setup_poll_session(client, fake_get)
        client._poll_loop()

        assert call_count == 3
        assert client._polling is False

    def test_resets_errors_on_success(self):
        """Consecutive error counter resets after a successful response."""
        client = _make_client()
        call_count = 0
        sleep_calls = []

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count <= 2:
                # Two errors
                resp.json.return_value = {"ok": False}
            elif call_count == 3:
                # Success — resets counter
                resp.json.return_value = {"ok": True, "result": []}
            elif call_count == 4:
                # Another error — backoff should restart from small value
                resp.json.return_value = {"ok": False}
            else:
                client._polling = False
                resp.json.return_value = {"ok": True, "result": []}
            return resp

        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        _setup_poll_session(client, fake_get)
        with patch("daemon.telegram.time.sleep", side_effect=fake_sleep):
            client._poll_loop()

        # After success at call 3, the error at call 4 should have
        # consecutive_errors=1 so backoff = 2^1 = 2
        assert call_count == 5
        assert sleep_calls[-1] == 2  # Reset backoff after success

    def test_timeout_does_not_count_as_error(self):
        """requests.exceptions.Timeout is normal for long-polling, not an error."""
        client = _make_client()
        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise requests.exceptions.Timeout()
            client._polling = False
            resp = MagicMock()
            resp.json.return_value = {"ok": True, "result": []}
            return resp

        _setup_poll_session(client, fake_get)
        with patch("daemon.telegram.time.sleep") as mock_sleep:
            client._poll_loop()

        # Timeouts should NOT trigger sleep (no backoff)
        mock_sleep.assert_not_called()
        assert call_count == 4

    def test_exits_cleanly_when_session_closed(self):
        """Poll loop exits without backoff when session is closed by stop_polling."""
        client = _make_client()
        call_count = 0

        def fake_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate session.close() interrupting the request
                client._polling = False
                raise ConnectionError("Session closed")
            resp = MagicMock()
            resp.json.return_value = {"ok": True, "result": []}
            return resp

        _setup_poll_session(client, fake_get)
        with patch("daemon.telegram.time.sleep") as mock_sleep:
            client._poll_loop()

        # Should exit immediately without sleeping (no backoff)
        mock_sleep.assert_not_called()
        assert call_count == 1


class TestGracefulShutdown:

    def test_stop_polling_closes_session(self):
        """stop_polling() closes the requests.Session to interrupt blocking calls."""
        client = _make_client()
        mock_session = MagicMock()
        client._poll_session = mock_session
        client._polling = True
        # No thread to join
        client._poll_thread = None

        client.stop_polling()

        mock_session.close.assert_called_once()
        assert client._poll_session is None
        assert client._polling is False

    def test_stop_polling_without_session(self):
        """stop_polling() handles case where session was never created."""
        client = _make_client()
        client._polling = False
        client._poll_session = None
        client._poll_thread = None

        client.stop_polling()  # Should not raise

    def test_start_polling_creates_session(self):
        """start_polling() creates a requests.Session for the poll loop."""
        client = _make_client()
        client.start_polling()

        assert client._poll_session is not None
        assert client._polling is True

        # Clean up
        client.stop_polling()
