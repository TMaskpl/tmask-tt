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

    def _run_pipe(self, log_callback: Callable[[str, str], None], strip_collation: bool) -> tuple:
        dump_cmd = self._build_mysqldump_cmd()
        mysql_cmd = self._build_mysql_cmd()
        dump_env = {**os.environ, 'MYSQL_PWD': self.params['source_password']}
        mysql_env = {**os.environ, 'MYSQL_PWD': self.params['dest_password']}

        dump_proc = subprocess.Popen(  # nosec B603
            dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dump_env,
        )
        feed_stdout = dump_proc.stdout
        sed_proc = None
        if strip_collation:
            sed_proc = subprocess.Popen(  # nosec B603 — static sed pattern, no user input
                ['sed', SED_STRIP_MYSQL80_COLLATION], stdin=dump_proc.stdout, stdout=subprocess.PIPE, text=True,
            )
            dump_proc.stdout.close()
            feed_stdout = sed_proc.stdout

        mysql_proc = subprocess.Popen(  # nosec B603
            mysql_cmd, stdin=feed_stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=mysql_env,
        )
        feed_stdout.close()

        output_lines = []
        output_lock = threading.Lock()

        def _drain(stream):
            for line in stream:
                line = line.rstrip()
                if line:
                    with output_lock:
                        output_lines.append(line)
                    log_callback('info', line)

        threads = [threading.Thread(target=_drain, args=(mysql_proc.stderr,)),
                   threading.Thread(target=_drain, args=(dump_proc.stderr,))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        mysql_exit = mysql_proc.wait()
        if sed_proc:
            sed_proc.wait()
        dump_exit = dump_proc.wait()
        return dump_exit, mysql_exit, '\n'.join(output_lines)

    def _check_output(self, output: str) -> None:
        lowered = output.lower()
        if 'access denied' in lowered:
            raise MysqlTransferError('AUTH FAILED — sprawdź dane uwierzytelniania')
        if self.params.get('table_name') and "doesn't exist" in lowered:
            raise MysqlTransferError(f'TABLE NOT FOUND: {self.params["table_name"]}')

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        strip_collation = self._dest_needs_collation_strip(log_callback)
        last_dump_exit = last_mysql_exit = None
        for attempt in range(1, MYSQL_DUMP_MAX_RETRIES + 1):
            log_callback('info', f'Starting mysqldump|mysql (attempt {attempt})')
            last_dump_exit, last_mysql_exit, output = self._run_pipe(log_callback, strip_collation)
            self._check_output(output)
            if last_dump_exit == 0 and last_mysql_exit == 0:
                log_callback('info', 'Transfer complete')
                if self.params.get('verify_row_count'):
                    self._verify_row_counts(log_callback)
                return
            if attempt < MYSQL_DUMP_MAX_RETRIES:
                log_callback('warn', f'mysqldump/mysql failed (dump={last_dump_exit}, mysql={last_mysql_exit}), retrying in {MYSQL_DUMP_RETRY_DELAY}s...')
                time.sleep(MYSQL_DUMP_RETRY_DELAY)

        raise MysqlTransferError(
            f'TRANSFER FAILED — mysqldump/mysql failed after {MYSQL_DUMP_MAX_RETRIES} attempts '
            f'(dump exit={last_dump_exit}, mysql exit={last_mysql_exit})'
        )

    def _verify_row_counts(self, log_callback: Callable[[str, str], None]) -> None:
        p = self.params
        try:
            src_conn = pymysql.connect(host=p['source_host'], port=p['source_port'], user=p['source_username'],
                                        password=p['source_password'], database=p['source_db_name'], connect_timeout=10)
        except pymysql.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć ze źródłem: {e}')
            return
        try:
            dst_conn = pymysql.connect(host=p['dest_host'], port=p['dest_port'], user=p['dest_username'],
                                        password=p['dest_password'], database=p['dest_db_name'], connect_timeout=10)
        except pymysql.Error as e:
            src_conn.close()
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć z celem: {e}')
            return
        try:
            if p.get('table_name'):
                tables = [p['table_name']]
            else:
                with src_conn.cursor() as cur:
                    cur.execute(
                        'SELECT table_name FROM information_schema.tables WHERE table_schema = %s',
                        (p['source_db_name'],),
                    )
                    tables = [row[0] for row in cur.fetchall()]
            for table in tables:
                with src_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM `{table}`')  # nosec B608 — table name from information_schema/user-selected dropdown, not raw user text input
                    src_count = cur.fetchone()[0]
                with dst_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM `{table}`')  # nosec B608
                    dst_count = cur.fetchone()[0]
                if src_count != dst_count:
                    log_callback('warn', f'ROW COUNT MISMATCH w "{table}": source={src_count} dest={dst_count}')
                else:
                    log_callback('info', f'ROW COUNT OK w "{table}": {src_count}')
        except pymysql.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION FAILED — {e}')
        finally:
            src_conn.close()
            dst_conn.close()
