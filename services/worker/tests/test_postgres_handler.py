import pytest
from unittest.mock import patch, MagicMock

from modules.postgres.handler import PgTransferHandler, PgTransferError
from modules.postgres.config import PG_DUMP_MAX_RETRIES, PG_DUMP_RETRY_DELAY


class TestPgTransferHandler:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': '10.0.0.1', 'source_port': 5432, 'source_username': 'postgres',
            'source_password': 'srcpass', 'source_db_name': 'proddb',
            'dest_host': '10.0.0.2', 'dest_port': 5432, 'dest_username': 'postgres',
            'dest_password': 'dstpass', 'dest_db_name': 'testdb',
            'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_builds_whole_db_pg_dump_command(self):
        handler = PgTransferHandler(self._make_params())
        cmd = handler._build_pg_dump_cmd()
        assert cmd[0] == 'pg_dump'
        assert '-h' in cmd and '10.0.0.1' in cmd
        assert '--clean' in cmd and '--if-exists' in cmd and '--no-owner' in cmd and '--no-privileges' in cmd
        assert '--table' not in cmd
        assert cmd[-1] == 'proddb'

    def test_builds_single_table_pg_dump_command(self):
        handler = PgTransferHandler(self._make_params(table_name='users'))
        cmd = handler._build_pg_dump_cmd()
        assert '--table' in cmd
        assert cmd[cmd.index('--table') + 1] == 'users'

    def test_builds_psql_command(self):
        handler = PgTransferHandler(self._make_params())
        cmd = handler._build_psql_cmd()
        assert cmd[0] == 'psql'
        assert '10.0.0.2' in cmd
        assert 'testdb' in cmd
