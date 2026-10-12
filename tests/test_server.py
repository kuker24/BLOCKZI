from unittest.mock import patch
import pytest

import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / 'copilot'))

import blockzi_config as cfg
import server


@pytest.fixture
def client():
    server.app.config['TESTING'] = True
    with server.app.test_client() as c:
        yield c


def test_server_import_and_default_host():
    """Verify default host is 127.0.0.1 and server modules load cleanly."""
    assert cfg.HOST == "127.0.0.1"


def test_index_route(client):
    """GET / should render the dashboard."""
    res = client.get('/')
    assert res.status_code == 200
    assert b'BLOCKZI' in res.data or b'Blockzi' in res.data


def test_auto_csrf_origin_mismatch(client):
    """POST /api/auto with mismatching Origin should return 403."""
    res = client.post(
        '/api/auto',
        json={'enabled': False},
        headers={'Origin': 'http://evil.com'}
    )
    assert res.status_code == 403
    data = res.get_json()
    assert 'Origin mismatch' in data.get('message', '')


def test_action_token_auth(client, monkeypatch):
    """When BLOCKZI_TOKEN is set, requests without valid token must return 401."""
    monkeypatch.setattr(cfg, 'TOKEN', 'secret123')

    # Without token -> 401
    res = client.post('/api/action', json={'action': 'retry'})
    assert res.status_code == 401

    # With invalid token -> 401
    res = client.post(
        '/api/action',
        json={'action': 'retry'},
        headers={'X-Blockzi-Token': 'wrong'}
    )
    assert res.status_code == 401

    # With valid Bearer token -> passes auth (device not connected -> 400)
    with patch('server.is_device_connected', return_value=True), \
         patch('subprocess.run') as mock_run:
        res = client.post(
            '/api/action',
            json={'action': 'retry'},
            headers={'Authorization': 'Bearer secret123'}
        )
        assert res.status_code == 200
        assert res.get_json().get('status') == 'ok'
        mock_run.assert_called_once()


def test_action_coordinate_validation(client):
    """Tap coordinates must be integers within screen bounds."""
    with patch('server.is_device_connected', return_value=True):
        # Out of bounds x
        res = client.post('/api/action', json={'action': 'tap', 'x': 2000, 'y': 1000})
        assert res.status_code == 400
        assert 'out of bounds' in res.get_json().get('message', '').lower()

        # Out of bounds y
        res = client.post('/api/action', json={'action': 'tap', 'x': 500, 'y': 3500})
        assert res.status_code == 400

        # Invalid type
        res = client.post('/api/action', json={'action': 'tap', 'x': 'not-an-int', 'y': 100})
        assert res.status_code == 400
