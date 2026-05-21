import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from celery import Celery
from celery.utils.log import get_task_logger
from apps.transfers.models import TransferJob, TransferLog
from modules.sftp.handler import SFTPHandler, SFTPTransferError
from modules.rsync.handler import RsyncHandler, RsyncTransferError

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

@app.task(bind=True, name='transfers.execute')
def execute_transfer(self, job_id: int):
    try:
        job = TransferJob.objects.get(pk=job_id)
    except TransferJob.DoesNotExist:
        logger.error(f'TransferJob {job_id} not found — task aborted')
        return
    job.mark_running(self.request.id)

    def log_callback(level: str, message: str):
        TransferLog.objects.create(job=job, level=level, message=message)

    params = _build_params(job)
    handler_cls = SFTPHandler if job.connection.protocol == 'sftp' else RsyncHandler

    try:
        handler_cls(params).execute(log_callback=log_callback)
        job.mark_done()
    except (SFTPTransferError, RsyncTransferError) as e:
        job.mark_failed(str(e))
        log_callback('error', str(e))
        logger.error(f'Transfer job {job_id} failed: {e}')
    except Exception as e:
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        log_callback('error', f'UNEXPECTED ERROR — {e}')
        logger.error(f'Transfer job {job_id} unexpected error: {e}')
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
