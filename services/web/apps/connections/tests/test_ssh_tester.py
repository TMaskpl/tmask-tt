from unittest.mock import MagicMock, patch

import pytest

from apps.connections.ssh_tester import test_connection as _test_connection


@pytest.mark.django_db
class TestSSHTesterMessages:
    def test_success_message_is_short_no_redundant_host_port(self, regular_user, make_connection):
        conn = make_connection(regular_user, host='10.0.0.1', port=22)
        mock_client = MagicMock()
        with patch('apps.connections.ssh_tester.paramiko.SSHClient', return_value=mock_client):
            result = _test_connection(conn)
        assert result.success is True
        # Host:port już widoczne w kolumnach tabeli — komunikat ma być krótki i niepowtarzalny
        assert result.message == 'CONNECTION OK'
