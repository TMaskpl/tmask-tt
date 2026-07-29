import os
import re
import subprocess  # nosec B404
import threading
import time
from typing import Callable

import pymysql

from modules.masking.faker_engine import mask_value

from .config import (
    MYSQL_DUMP_BASE_FLAGS,
    MYSQL_DUMP_MAX_RETRIES,
    MYSQL_DUMP_RETRY_DELAY,
)


class MysqlTransferError(Exception):
    pass


class MysqlTransferHandler:
    def __init__(self, params: dict):
        self.params = params
        self._log_callback = None
        self._whole_db_scope = not self.params.get('table_name')
        self._column_lengths = {}

    def _build_mysqldump_cmd(self) -> list:
        p = self.params
        cmd = ['mysqldump', '-h', p['source_host'], '-P', str(p['source_port']), '-u', p['source_username']]
        cmd += list(MYSQL_DUMP_BASE_FLAGS)
        if p.get('masking_rules'):
            cmd += ['--skip-extended-insert', '--complete-insert']
        cmd.append(p['source_db_name'])
        if p.get('table_name'):
            cmd.append(p['table_name'])
        return cmd

    def _build_mysql_cmd(self) -> list:
        p = self.params
        return ['mysql', '-h', p['dest_host'], '-P', str(p['dest_port']), '-u', p['dest_username'], p['dest_db_name']]

    def _quote_identifier(self, name: str) -> str:
        # pymysql has no sql.Identifier()-equivalent safe-quoting API (unlike
        # psycopg2's psycopg2.sql module used in modules/postgres/handler.py).
        # The standard, driver-agnostic defense — also used by SQLAlchemy's
        # MySQL dialect — is to wrap the identifier in backticks and double
        # any backtick characters found inside it.
        return '`' + name.replace('`', '``') + '`'

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

    def _fetch_column_lengths(self) -> dict:
        masking_rules = self.params.get('masking_rules', {})
        if not masking_rules:
            return {}
        p = self.params
        try:
            conn = pymysql.connect(
                host=p['source_host'], port=p['source_port'], user=p['source_username'],
                password=p['source_password'], database=p['source_db_name'], connect_timeout=10,
            )
        except pymysql.Error:
            return {}
        result = {}
        try:
            with conn.cursor() as cur:
                for table, columns in masking_rules.items():
                    placeholders = ','.join(['%s'] * len(columns))
                    cur.execute(
                        f'SELECT column_name, character_maximum_length FROM information_schema.columns '
                        f'WHERE table_schema = %s AND table_name = %s AND column_name IN ({placeholders})',
                        (p['source_db_name'], table, *columns.keys()),
                    )
                    result[table] = dict(cur.fetchall())
        except pymysql.Error:
            return {}
        finally:
            conn.close()
        return result

    _INSERT_RE = re.compile(r"^INSERT INTO `([^`]+)` \(([^)]*)\) VALUES \((.*)\);\n?$")

    def _split_values(self, values_str: str) -> list:
        # --complete-insert z mysqldump generuje jeden wiersz per INSERT (bo
        # --skip-extended-insert wymusza brak batchowania) — string wartości
        # to prosta lista rozdzielona przecinkami z opcjonalnym cudzysłowem;
        # tokenizer musi respektować przecinki WEWNĄTRZ cudzysłowu.
        values = []
        current = ''
        in_quotes = False
        i = 0
        while i < len(values_str):
            ch = values_str[i]
            if ch == "'" and (i == 0 or values_str[i - 1] != '\\'):
                in_quotes = not in_quotes
                current += ch
            elif ch == ',' and not in_quotes:
                values.append(current)
                current = ''
            else:
                current += ch
            i += 1
        values.append(current)
        return values

    def _quote_mysql_value(self, value: str) -> str:
        escaped = value.replace('\\', '\\\\').replace("'", "\\'")
        return f"'{escaped}'"

    def _relay_lines(self, lines, strip_collation: bool):
        warned_tables = set()
        for line in lines:
            if strip_collation:
                line = line.replace(' COLLATE utf8mb4_0900_ai_ci', '')
            match = self._INSERT_RE.match(line)
            if not match:
                yield line
                continue
            table, columns_str, values_str = match.groups()
            columns = [c.strip().strip('`') for c in columns_str.split(',')]
            rules = self.params.get('masking_rules', {}).get(table, {})
            if not rules:
                if self._whole_db_scope and table not in warned_tables and self._log_callback:
                    self._log_callback('warn', f'Tabela "{table}" przesłana BEZ maskowania — brak zdefiniowanego profilu')
                    warned_tables.add(table)
                yield line
                continue
            values = self._split_values(values_str)
            for i, col in enumerate(columns):
                if col in rules and i < len(values):
                    values[i] = self._quote_mysql_value(
                        mask_value(rules[col], max_length=self._column_lengths.get(table, {}).get(col))
                    )
            yield f"INSERT INTO `{table}` ({columns_str}) VALUES ({','.join(values)});\n"

    def _run_pipe(self, log_callback: Callable[[str, str], None], strip_collation: bool) -> tuple:
        dump_cmd = self._build_mysqldump_cmd()
        mysql_cmd = self._build_mysql_cmd()
        dump_env = {**os.environ, 'MYSQL_PWD': self.params['source_password']}
        mysql_env = {**os.environ, 'MYSQL_PWD': self.params['dest_password']}

        dump_proc = subprocess.Popen(  # nosec B603
            dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='surrogateescape', env=dump_env,
        )
        mysql_proc = subprocess.Popen(  # nosec B603
            mysql_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='surrogateescape', env=mysql_env,
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
                for line in self._relay_lines(dump_proc.stdout, strip_collation):
                    mysql_proc.stdin.write(line)
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    mysql_proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
                dump_proc.stdout.close()

        threads = [
            threading.Thread(target=_drain, args=(mysql_proc.stderr,)),
            threading.Thread(target=_drain, args=(dump_proc.stderr,)),
        ]
        relay_thread = threading.Thread(target=_relay)
        for t in threads:
            t.start()
        relay_thread.start()
        for t in threads:
            t.join()
        relay_thread.join()

        mysql_exit = mysql_proc.wait()
        dump_exit = dump_proc.wait()
        return dump_exit, mysql_exit, '\n'.join(output_lines)

    def _check_output(self, output: str) -> None:
        lowered = output.lower()
        if 'access denied' in lowered:
            raise MysqlTransferError('AUTH FAILED — sprawdź dane uwierzytelniania')
        if self.params.get('table_name') and "doesn't exist" in lowered:
            raise MysqlTransferError(f'TABLE NOT FOUND: {self.params["table_name"]}')

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        self._log_callback = log_callback
        self._column_lengths = self._fetch_column_lengths()
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
                quoted_table = self._quote_identifier(table)
                with src_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM {quoted_table}')  # nosec B608 — identifier is safely quoted via _quote_identifier, not raw-interpolated
                    src_count = cur.fetchone()[0]
                with dst_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM {quoted_table}')  # nosec B608 — identifier is safely quoted via _quote_identifier, not raw-interpolated
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
