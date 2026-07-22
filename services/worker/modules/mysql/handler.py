import os
import subprocess  # nosec B404
import threading
import time
from typing import Callable

import pymysql

from .config import (
    MYSQL_DUMP_BASE_FLAGS,
    MYSQL_DUMP_MAX_RETRIES,
    MYSQL_DUMP_RETRY_DELAY,
    SED_STRIP_MYSQL80_COLLATION,
)


class MysqlTransferError(Exception):
    pass


class MysqlTransferHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_mysqldump_cmd(self) -> list:
        p = self.params
        cmd = ['mysqldump', '-h', p['source_host'], '-P', str(p['source_port']), '-u', p['source_username']]
        cmd += list(MYSQL_DUMP_BASE_FLAGS)
        cmd.append(p['source_db_name'])
        if p.get('table_name'):
            cmd.append(p['table_name'])
        return cmd

    def _build_mysql_cmd(self) -> list:
        p = self.params
        return ['mysql', '-h', p['dest_host'], '-P', str(p['dest_port']), '-u', p['dest_username'], p['dest_db_name']]

    def _dest_needs_collation_strip(self, log_callback: Callable[[str, str], None] = None) -> bool:
        p = self.params
        try:
            with pymysql.connect(host=p['dest_host'], port=p['dest_port'], user=p['dest_username'],
                                  password=p['dest_password'], connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT VERSION()')
                    version_str = cur.fetchone()[0]
            major = int(version_str.split('.')[0])
            return major < 8
        except (pymysql.Error, ValueError, IndexError) as e:
            if log_callback:
                log_callback('warn', f'VERSION CHECK FAILED — nie udało się wykryć wersji serwera docelowego dla sprawdzenia zgodności COLLATION: {e}. Zakładam brak konfliktu.')
            return False
