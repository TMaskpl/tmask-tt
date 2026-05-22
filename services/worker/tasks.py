import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from celery import Celery
from celery.utils.log import get_task_logger
from apps.transfers.models import TransferJob, TransferLog
from modules.sftp.handler import SFTPHandler, SFTPTransferError
from modules.rsync.handler import RsyncHandler, RsyncTransferError
from modules.relay.handler import RelayHandler, RelayTransferError
from notifications import send_email_notification

app = Celery('transporter')
app.config_from_object('django.conf:settings', namespace='CELERY')

logger = get_task_logger(__name__)


def _build_params(job: TransferJob) -> dict:
    conn = job.connection
    return {
        'host': conn.host,
        'port': conn.port,
        'username': conn.username,
        'password': conn.password,
        'ssh_key': conn.ssh_key,
        'source_path': job.source_path,
        'destination_path': job.destination_path,
        'compress': conn.compress,
        'encrypt': conn.encrypt,
        'strict_host_key_checking': conn.strict_host_key_checking,
        'known_host_key': conn.known_host_key,
    }


def _build_relay_params(flow) -> tuple:
    def _conn_params(conn, source_path, destination_path):
        return {
            'host': conn.host,
            'port': conn.port,
            'username': conn.username,
            'password': conn.password,
            'ssh_key': conn.ssh_key,
            'source_path': source_path,
            'destination_path': destination_path,
            'strict_host_key_checking': conn.strict_host_key_checking,
            'known_host_key': conn.known_host_key,
        }
    source_params = _conn_params(flow.source_conn, flow.source_path, flow.source_path)
    dest_params = _conn_params(flow.dest_conn, flow.source_path, flow.dest_path)
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


@app.task(bind=True, name='transfers.execute')
def execute_transfer(self, job_id: int = None, scheduled_id: int = None):
    if job_id is None and scheduled_id is not None:
        job = _create_job_from_schedule(scheduled_id)
        if job is None:
            return
    else:
        try:
            job = TransferJob.objects.get(pk=job_id)
        except TransferJob.DoesNotExist:
            logger.error(f'TransferJob {job_id} not found — task aborted')
            return

    job.mark_running(self.request.id)

    def log_callback(level: str, message: str):
        TransferLog.objects.create(job=job, level=level, message=message)

    try:
        if job.flow_id:
            source_params, dest_params = _build_relay_params(job.flow)
            RelayHandler(source_params, dest_params).execute(log_callback=log_callback)
        else:
            params = _build_params(job)
            handler_cls = SFTPHandler if job.connection.protocol == 'sftp' else RsyncHandler
            handler_cls(params).execute(log_callback=log_callback)
        job.mark_done()
        send_notification.delay(job.pk)
    except (SFTPTransferError, RsyncTransferError, RelayTransferError) as e:
        job.mark_failed(str(e))
        send_notification.delay(job.pk)
        log_callback('error', str(e))
        logger.error(f'Transfer job {job.pk} failed: {e}')
    except Exception as e:
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        send_notification.delay(job.pk)
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
