import os
import re
import subprocess  # nosec B404
import threading
import time
from typing import Callable

import psycopg2
from psycopg2 import sql

from modules.masking.faker_engine import mask_value

from .config import (
    PG_DUMP_BASE_FLAGS,
    PG_DUMP_MAX_RETRIES,
    PG_DUMP_RETRY_DELAY,
)


class PgTransferError(Exception):
    pass


class PgTransferHandler:
    def __init__(self, params: dict):
        self.params = params
        self._log_callback = None
        self._whole_db_scope = not self.params.get('table_name')
        self._column_lengths = {}

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

    _COPY_HEADER_RE = re.compile(r'^COPY (\S+) \(([^)]*)\) FROM stdin;\n?$')

    def _fetch_column_lengths(self) -> dict:
        """Introspects character_maximum_length for every column referenced by
        masking_rules — best-effort: jeśli introspekcja się nie uda, maskowanie
        nadal działa, po prostu bez obcinania (mask_value akceptuje max_length=None)."""
        masking_rules = self.params.get('masking_rules', {})
        if not masking_rules:
            return {}
        p = self.params
        try:
            conn = psycopg2.connect(
                host=p['source_host'], port=p['source_port'], user=p['source_username'],
                password=p['source_password'], dbname=p['source_db_name'], connect_timeout=10,
            )
        except psycopg2.Error:
            return {}
        result = {}
        try:
            with conn.cursor() as cur:
                for table, columns in masking_rules.items():
                    cur.execute(
                        "SELECT column_name, character_maximum_length FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = %s AND column_name = ANY(%s)",
                        (table, list(columns.keys())),
                    )
                    result[table] = dict(cur.fetchall())
        except psycopg2.Error:
            return {}
        finally:
            conn.close()
        return result

    def _relay_lines(self, lines):
        current_table = None
        current_columns = []
        current_rules = {}
        warned_tables = set()
        for line in lines:
            if line.startswith('SET transaction_timeout'):
                continue
            header = self._COPY_HEADER_RE.match(line)
            if header:
                current_table = header.group(1)
                if '.' in current_table:
                    current_table = current_table.split('.', 1)[1]
                current_table = current_table.strip('"')
                current_columns = [c.strip() for c in header.group(2).split(',')]
                current_rules = self.params.get('masking_rules', {}).get(current_table, {})
                if not current_rules and self._whole_db_scope and current_table not in warned_tables and self._log_callback:
                    self._log_callback('warn', f'Tabela "{current_table}" przesłana BEZ maskowania — brak zdefiniowanego profilu')
                    warned_tables.add(current_table)
                yield line
                continue
            if current_table and line != '\\.\n' and current_rules:
                values = line.rstrip('\n').split('\t')
                for i, col in enumerate(current_columns):
                    if col in current_rules and i < len(values):
                        values[i] = mask_value(
                            current_rules[col],
                            max_length=self._column_lengths.get(current_table, {}).get(col),
                        )
                yield '\t'.join(values) + '\n'
                continue
            if line == '\\.\n':
                current_table = None
                current_columns = []
                current_rules = {}
            yield line

    def _run_pipe(self, log_callback: Callable[[str, str], None]) -> tuple:
        dump_cmd = self._build_pg_dump_cmd()
        psql_cmd = self._build_psql_cmd()
        dump_env = {**os.environ, 'PGPASSWORD': self.params['source_password']}
        psql_env = {**os.environ, 'PGPASSWORD': self.params['dest_password']}

        dump_proc = subprocess.Popen(  # nosec B603 — cmd built from validated connection params, no shell=True
            dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='surrogateescape', env=dump_env,
        )
        psql_proc = subprocess.Popen(  # nosec B603
            psql_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='surrogateescape', env=psql_env,
        )

        output_lines = []
        output_lock = threading.Lock()

        def _drain(stream):
            for line in stream:
                line = line.rstrip()
                if line:
                    with output_lock:
                        output_lines.append(line)
                    log_callback('info', line)

        def _relay():
            try:
                for line in self._relay_lines(dump_proc.stdout):
                    psql_proc.stdin.write(line)
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    psql_proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
                dump_proc.stdout.close()

        psql_thread = threading.Thread(target=_drain, args=(psql_proc.stderr,))
        dump_thread = threading.Thread(target=_drain, args=(dump_proc.stderr,))
        relay_thread = threading.Thread(target=_relay)
        psql_thread.start()
        dump_thread.start()
        relay_thread.start()
        psql_thread.join()
        dump_thread.join()
        relay_thread.join()

        psql_exit = psql_proc.wait()
        dump_exit = dump_proc.wait()
        return dump_exit, psql_exit, '\n'.join(output_lines)

    def _check_output(self, output: str) -> None:
        lowered = output.lower()
        if 'authentication failed' in lowered:
            raise PgTransferError('AUTH FAILED — sprawdź dane uwierzytelniania')
        if self.params.get('table_name') and 'does not exist' in lowered:
            raise PgTransferError(f'TABLE NOT FOUND: {self.params["table_name"]}')
        # 'could not connect'/'connection refused' are deliberately NOT raised here —
        # they're transient network conditions (dest restarting, brief outage) and
        # should retry like any other pg_dump/psql exit-code failure, not fail fast.

    def _verify_row_counts(self, log_callback: Callable[[str, str], None]) -> None:
        p = self.params
        try:
            src_conn = psycopg2.connect(host=p['source_host'], port=p['source_port'], user=p['source_username'],
                                         password=p['source_password'], dbname=p['source_db_name'])
        except psycopg2.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć ze źródłem: {e}')
            return

        try:
            dst_conn = psycopg2.connect(host=p['dest_host'], port=p['dest_port'], user=p['dest_username'],
                                         password=p['dest_password'], dbname=p['dest_db_name'])
        except psycopg2.Error as e:
            src_conn.close()
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć z celem: {e}')
            return

        try:
            if p.get('table_name'):
                tables = [p['table_name']]
            else:
                with src_conn.cursor() as cur:
                    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    tables = [row[0] for row in cur.fetchall()]
            for table in tables:
                count_query = sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(table))
                with src_conn.cursor() as cur:
                    cur.execute(count_query)
                    src_count = cur.fetchone()[0]
                with dst_conn.cursor() as cur:
                    cur.execute(count_query)
                    dst_count = cur.fetchone()[0]
                if src_count != dst_count:
                    log_callback('warn', f'ROW COUNT MISMATCH w "{table}": source={src_count} dest={dst_count}')
                else:
                    log_callback('info', f'ROW COUNT OK w "{table}": {src_count}')
        except psycopg2.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION FAILED — {e}')
        finally:
            src_conn.close()
            dst_conn.close()

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        self._log_callback = log_callback
        self._column_lengths = self._fetch_column_lengths()
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
