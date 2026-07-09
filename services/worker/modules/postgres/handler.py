import os
import subprocess  # nosec B404
import threading
import time
from typing import Callable

import psycopg2

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

    def _run_pipe(self, log_callback: Callable[[str, str], None]) -> tuple:
        dump_cmd = self._build_pg_dump_cmd()
        psql_cmd = self._build_psql_cmd()
        dump_env = {**os.environ, 'PGPASSWORD': self.params['source_password']}
        psql_env = {**os.environ, 'PGPASSWORD': self.params['dest_password']}

        dump_proc = subprocess.Popen(  # nosec B603 — cmd built from validated connection params, no shell=True
            dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dump_env,
        )
        psql_proc = subprocess.Popen(  # nosec B603
            psql_cmd, stdin=dump_proc.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=psql_env,
        )
        dump_proc.stdout.close()

        output_lines = []
        output_lock = threading.Lock()

        def _drain(stream):
            for line in stream:
                line = line.rstrip()
                if line:
                    with output_lock:
                        output_lines.append(line)
                    log_callback('info', line)

        psql_thread = threading.Thread(target=_drain, args=(psql_proc.stderr,))
        dump_thread = threading.Thread(target=_drain, args=(dump_proc.stderr,))
        psql_thread.start()
        dump_thread.start()
        psql_thread.join()
        dump_thread.join()

        psql_exit = psql_proc.wait()
        dump_exit = dump_proc.wait()
        return dump_exit, psql_exit, '\n'.join(output_lines)

    def _check_output(self, output: str) -> None:
        lowered = output.lower()
        if 'authentication failed' in lowered:
            raise PgTransferError('AUTH FAILED — sprawdź dane uwierzytelniania')
        if self.params.get('table_name') and 'does not exist' in lowered:
            raise PgTransferError(f'TABLE NOT FOUND: {self.params["table_name"]}')
        if 'could not connect' in lowered or 'connection refused' in lowered:
            raise PgTransferError(
                f'CONNECTION FAILED — sprawdź host/port ({self.params["source_host"]} / {self.params["dest_host"]})'
            )

    def _verify_row_counts(self, log_callback: Callable[[str, str], None]) -> None:
        p = self.params
        src_conn = psycopg2.connect(host=p['source_host'], port=p['source_port'], user=p['source_username'],
                                     password=p['source_password'], dbname=p['source_db_name'])
        dst_conn = psycopg2.connect(host=p['dest_host'], port=p['dest_port'], user=p['dest_username'],
                                     password=p['dest_password'], dbname=p['dest_db_name'])
        try:
            if p.get('table_name'):
                tables = [p['table_name']]
            else:
                with src_conn.cursor() as cur:
                    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    tables = [row[0] for row in cur.fetchall()]
            for table in tables:
                with src_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                    src_count = cur.fetchone()[0]
                with dst_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                    dst_count = cur.fetchone()[0]
                if src_count != dst_count:
                    log_callback('warn', f'ROW COUNT MISMATCH w "{table}": source={src_count} dest={dst_count}')
                else:
                    log_callback('info', f'ROW COUNT OK w "{table}": {src_count}')
        finally:
            src_conn.close()
            dst_conn.close()

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        last_dump_exit = last_psql_exit = None
        for attempt in range(1, PG_DUMP_MAX_RETRIES + 1):
            log_callback('info', f'Starting pg_dump|psql (attempt {attempt})')
            last_dump_exit, last_psql_exit, output = self._run_pipe(log_callback)
            self._check_output(output)
            if last_dump_exit == 0 and last_psql_exit == 0:
                log_callback('info', 'Transfer complete')
                if self.params.get('verify_row_count'):
                    self._verify_row_counts(log_callback)
                return
            if attempt < PG_DUMP_MAX_RETRIES:
                log_callback('warn', f'pg_dump/psql failed (dump={last_dump_exit}, psql={last_psql_exit}), retrying in {PG_DUMP_RETRY_DELAY}s...')
                time.sleep(PG_DUMP_RETRY_DELAY)

        raise PgTransferError(
            f'TRANSFER FAILED — pg_dump/psql failed after {PG_DUMP_MAX_RETRIES} attempts '
            f'(pg_dump exit={last_dump_exit}, psql exit={last_psql_exit})'
        )
