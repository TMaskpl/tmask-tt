import os
from pathlib import Path

import django

from celery import Celery
from celery.utils.log import get_task_logger

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from django.conf import settings  # noqa: E402
from apps.connections.models import Connection  # noqa: E402
from apps.transfers.models import TransferJob, TransferLog  # noqa: E402
from apps.db_transfers.models import DbTransferJob, DbTransferLog  # noqa: E402
from apps.masking.models import MaskingRule  # noqa: E402
from apps.webhook_deliveries.models import WebhookDeliveryLog  # noqa: E402
from apps.webhook_deliveries.services import (  # noqa: E402
    circuit_is_open, record_success, record_failure, CIRCUIT_SKIPPED_MESSAGE,
)
from modules.sftp.handler import SFTPHandler, SFTPTransferError  # noqa: E402
from modules.rsync.handler import RsyncHandler, RsyncTransferError  # noqa: E402
from modules.relay.handler import RelayHandler, RelayTransferError  # noqa: E402
from modules.postgres.handler import PgTransferHandler, PgTransferError  # noqa: E402
from modules.mysql.handler import MysqlTransferHandler, MysqlTransferError  # noqa: E402
from modules.mssql.handler import MssqlTransferHandler, MssqlTransferError  # noqa: E402
from notifications import send_email_notification, send_webhook_notification, send_telegram_notification  # noqa: E402

app = Celery('transporter')
app.config_from_object('django.conf:settings', namespace='CELERY')

logger = get_task_logger(__name__)


def _build_params(job: TransferJob, gpg_passphrase=None) -> dict:
    conn = job.connection
    return {
        'host': conn.host,
        'port': conn.port,
        'username': conn.username,
        'password': conn.password,
        'ssh_key': conn.ssh_key,
        'ssh_key_passphrase': conn.ssh_key_passphrase,
        'source_path': job.source_path,
        'destination_path': job.destination_path,
        'compress': conn.compress,
        'encrypt': conn.encrypt,
        'gpg_passphrase': gpg_passphrase,
        'strict_host_key_checking': conn.strict_host_key_checking,
        'known_host_key': conn.known_host_key,
        'dry_run': conn.dry_run_before_transfer,
        'verify_checksum': conn.verify_checksum,
    }


def _build_relay_params(flow) -> tuple:
    def _conn_params(conn, source_path, destination_path):
        return {
            'host': conn.host,
            'port': conn.port,
            'username': conn.username,
            'password': conn.password,
            'ssh_key': conn.ssh_key,
            'ssh_key_passphrase': conn.ssh_key_passphrase,
            'source_path': source_path,
            'destination_path': destination_path,
            'strict_host_key_checking': conn.strict_host_key_checking,
            'known_host_key': conn.known_host_key,
        }
    source_params = _conn_params(flow.source_conn, flow.source_path, flow.source_path)
    dest_params = _conn_params(flow.dest_conn, flow.source_path, flow.dest_path)
    source_params['verify_checksum'] = flow.verify_checksum
    return source_params, dest_params


def _create_job_from_schedule(scheduled_id: int):
    from django.utils import timezone
    from apps.scheduler.models import ScheduledTransfer
    try:
        sched = ScheduledTransfer.objects.get(pk=scheduled_id, enabled=True)
    except ScheduledTransfer.DoesNotExist:
        logger.error(f'ScheduledTransfer {scheduled_id} not found or disabled — skipping')
        return None
    if sched.flow_id:
        job = TransferJob.objects.create(
            owner=sched.owner,
            flow=sched.flow,
            source_path=sched.flow.source_path,
            destination_path=sched.flow.dest_path,
        )
    else:
        job = TransferJob.objects.create(
            owner=sched.owner,
            connection=sched.connection,
            source_path=sched.source_path,
            destination_path=sched.destination_path,
        )
    sched.last_run = timezone.now()
    sched.save(update_fields=['last_run'])
    return job


def _resolve_job(job_id: int | None, scheduled_id: int | None):
    if job_id is None and scheduled_id is not None:
        return _create_job_from_schedule(scheduled_id)
    try:
        return TransferJob.objects.get(pk=job_id)
    except TransferJob.DoesNotExist:
        logger.error(f'TransferJob {job_id} not found — task aborted')
        return None


def _run_transfer(job, gpg_passphrase: str | None, log_callback, progress_callback=None) -> None:
    if job.flow_id:
        source_params, dest_params = _build_relay_params(job.flow)
        RelayHandler(source_params, dest_params).execute(log_callback=log_callback)
    else:
        if job.connection.encrypt and gpg_passphrase is None:
            log_callback('warn', 'GPG encryption enabled but no passphrase provided — file will not be encrypted')
        params = _build_params(job, gpg_passphrase=gpg_passphrase)
        handler_cls = SFTPHandler if job.connection.protocol == 'sftp' else RsyncHandler
        handler_cls(params).execute(log_callback=log_callback, progress_callback=progress_callback)


@app.task(bind=True, name='transfers.send_notification', max_retries=3, default_retry_delay=60)
def send_notification(self, job_id: int):
    try:
        job = TransferJob.objects.select_related('owner', 'connection', 'flow').get(pk=job_id)
    except Exception:
        logger.error(f'TransferJob {job_id} not found — notification skipped')
        return
    try:
        send_email_notification(job)
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(bind=True, name='transfers.send_webhook', max_retries=3, default_retry_delay=60)
def send_webhook(self, job_id: int):
    try:
        job = TransferJob.objects.select_related('owner', 'connection', 'flow').get(pk=job_id)
    except Exception:
        logger.error(f'TransferJob {job_id} not found — webhook skipped')
        return
    user = job.owner
    if not user.webhook_url:
        return
    if circuit_is_open(user):
        WebhookDeliveryLog.objects.create(
            user=user, job=job, url=user.webhook_url,
            success=False, skipped=True, error_message=CIRCUIT_SKIPPED_MESSAGE,
        )
        return
    try:
        sent = send_webhook_notification(job)
    except Exception as exc:
        record_failure(user)
        WebhookDeliveryLog.objects.create(
            user=user, job=job, url=user.webhook_url, success=False, error_message=str(exc),
        )
        raise self.retry(exc=exc)
    if sent:
        record_success(user)
        WebhookDeliveryLog.objects.create(user=user, job=job, url=user.webhook_url, success=True)


@app.task(bind=True, name='transfers.send_telegram', max_retries=3, default_retry_delay=60)
def send_telegram(self, job_id: int):
    try:
        job = TransferJob.objects.select_related('owner', 'connection', 'flow').get(pk=job_id)
    except Exception:
        logger.error(f'TransferJob {job_id} not found — telegram skipped')
        return
    try:
        send_telegram_notification(job)
    except Exception as exc:
        raise self.retry(exc=exc)


def _cleanup_source_file(job) -> None:
    if job.connection_id is None:
        return  # flow/relay — source_path na zdalnym hoście, nie dotykamy
    path = job.source_path
    if not path:
        return
    try:
        if not Path(path).resolve().is_relative_to(Path(settings.TRANSFERS_DIR).resolve()):
            return
    except OSError as e:
        logger.warning(f'Nie udało się zweryfikować ścieżki {path}: {e}')
        return
    try:
        os.unlink(path)
    except OSError as e:
        logger.warning(f'Nie udało się usunąć {path} po transferze: {e}')


@app.task(bind=True, name='transfers.execute')
def execute_transfer(self, job_id: int | None = None, scheduled_id: int | None = None, gpg_passphrase: str | None = None):
    job = _resolve_job(job_id, scheduled_id)
    if job is None:
        return

    job.mark_running(self.request.id)

    def log_callback(level: str, message: str):
        TransferLog.objects.create(job=job, level=level, message=message)

    last_percent = None

    def progress_callback(percent: int):
        nonlocal last_percent
        if percent != last_percent:
            last_percent = percent
            job.update_progress(percent)

    try:
        _run_transfer(job, gpg_passphrase, log_callback, progress_callback=progress_callback)
        job.mark_done()
        _cleanup_source_file(job)
        send_notification.delay(job.pk)
        send_webhook.delay(job.pk)
        send_telegram.delay(job.pk)
    except (SFTPTransferError, RsyncTransferError, RelayTransferError) as e:
        job.mark_failed(str(e))
        send_notification.delay(job.pk)
        send_webhook.delay(job.pk)
        send_telegram.delay(job.pk)
        log_callback('error', str(e))
        logger.error(f'Transfer job {job.pk} failed: {e}')
    except Exception as e:
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        send_notification.delay(job.pk)
        send_webhook.delay(job.pk)
        send_telegram.delay(job.pk)
        log_callback('error', f'UNEXPECTED ERROR — {e}')
        logger.error(f'Transfer job {job.pk} unexpected error: {e}')
        raise


@app.task(name='transfers.cleanup_orphans')
def cleanup_orphan_jobs():
    from django.utils import timezone
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(hours=1)
    orphans = TransferJob.objects.filter(status='running', started_at__lt=cutoff)
    count = orphans.count()
    orphans.update(status='failed', error_message='TASK INTERRUPTED — worker restarted')
    logger.info(f'Cleaned up {count} orphaned jobs')


@app.task(name='transfers.cleanup_old_transfers')
def cleanup_old_transfers():
    import time
    if not os.path.isdir(settings.TRANSFERS_DIR):
        logger.warning(f'Retention: {settings.TRANSFERS_DIR} nie istnieje — pomijam')
        return
    cutoff = time.time() - settings.TRANSFERS_RETENTION_DAYS * 86400
    removed = 0
    for name in os.listdir(settings.TRANSFERS_DIR):
        path = os.path.join(settings.TRANSFERS_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.unlink(path)
                removed += 1
        except OSError as e:
            logger.warning(f'Retention: nie udało się usunąć {path}: {e}')
    logger.info(f'Retention: usunięto {removed} plików z {settings.TRANSFERS_DIR}')


@app.task(name='transfers.dry_run_preview')
def dry_run_preview(connection_id: int, source_path: str, destination_path: str, gpg_passphrase: str | None = None) -> dict:
    try:
        conn = Connection.objects.get(pk=connection_id)
    except Connection.DoesNotExist:
        return {'exit_code': None, 'output': f'Connection {connection_id} nie istnieje'}

    params = {
        'host': conn.host,
        'port': conn.port,
        'username': conn.username,
        'password': conn.password,
        'ssh_key': conn.ssh_key,
        'ssh_key_passphrase': conn.ssh_key_passphrase,
        'source_path': source_path,
        'destination_path': destination_path,
        'compress': conn.compress,
        'encrypt': conn.encrypt,
        'gpg_passphrase': gpg_passphrase,
        'strict_host_key_checking': conn.strict_host_key_checking,
        'known_host_key': conn.known_host_key,
    }

    def log_callback(level: str, message: str):
        logger.info(f'[dry-run preview] {level}: {message}') if level != 'warn' else logger.warning(f'[dry-run preview] {message}')

    return RsyncHandler(params).preview(log_callback)


def _db_transfer_handlers() -> dict:
    # Built fresh on each call (not as a module-level constant) so that
    # unittest.mock.patch('tasks.MysqlTransferHandler'/'PgTransferHandler'/...)
    # is honored — a module-level dict would freeze in the original class
    # objects at import time and silently ignore patched replacements.
    return {
        'postgres': (PgTransferHandler, PgTransferError),
        'mysql': (MysqlTransferHandler, MysqlTransferError),
        'mssql': (MssqlTransferHandler, MssqlTransferError),
    }


def _masking_rules_for(source_connection) -> dict:
    rules = MaskingRule.objects.filter(connection=source_connection).values(
        'table_name', 'column_name', 'faker_provider',
    )
    result = {}
    for r in rules:
        result.setdefault(r['table_name'], {})[r['column_name']] = r['faker_provider']
    return result


def _build_db_transfer_params(job) -> dict:
    return {
        'source_host': job.source_connection.host,
        'source_port': job.source_connection.port,
        'source_username': job.source_connection.username,
        'source_password': job.source_connection.password,
        'source_db_name': job.source_connection.db_name,
        'dest_host': job.dest_connection.host,
        'dest_port': job.dest_connection.port,
        'dest_username': job.dest_connection.username,
        'dest_password': job.dest_connection.password,
        'dest_db_name': job.dest_connection.db_name,
        'table_name': job.table_name or None,
        'verify_row_count': job.verify_row_count,
        'masking_rules': _masking_rules_for(job.source_connection),
    }


@app.task(bind=True, name='db_transfers.execute')
def execute_db_transfer(self, job_id: int):
    try:
        job = DbTransferJob.objects.select_related('source_connection', 'dest_connection').get(pk=job_id)
    except DbTransferJob.DoesNotExist:
        logger.error(f'DbTransferJob {job_id} not found — task aborted')
        return

    job.mark_running(self.request.id)

    def log_callback(level: str, message: str):
        DbTransferLog.objects.create(job=job, level=level, message=message)

    handler_cls, error_cls = _db_transfer_handlers()[job.engine]
    try:
        params = _build_db_transfer_params(job)
        handler_cls(params).execute(log_callback=log_callback)
        job.mark_done()
    except error_cls as e:
        job.mark_failed(str(e))
        log_callback('error', str(e))
        logger.error(f'DbTransferJob {job.pk} failed: {e}')
    except Exception as e:
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        log_callback('error', f'UNEXPECTED ERROR — {e}')
        logger.error(f'DbTransferJob {job.pk} unexpected error: {e}')
        raise
