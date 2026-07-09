import os
import subprocess  # nosec B404
import time
from typing import Callable

from .config import PG_DUMP_BASE_FLAGS, PG_DUMP_MAX_RETRIES, PG_DUMP_RETRY_DELAY


class PgTransferError(Exception):
    pass


class PgTransferHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_pg_dump_cmd(self) -> list:
        p = self.params
        cmd = ['pg_dump', '-h', p['source_host'], '-p', str(p['source_port']), '-U', p['source_username']]
        cmd += list(PG_DUMP_BASE_FLAGS)
        if p.get('table_name'):
            cmd += ['--table', p['table_name']]
        cmd.append(p['source_db_name'])
        return cmd

    def _build_psql_cmd(self) -> list:
        p = self.params
        return [
            'psql', '-h', p['dest_host'], '-p', str(p['dest_port']), '-U', p['dest_username'],
            '-v', 'ON_ERROR_STOP=1', p['dest_db_name'],
        ]
