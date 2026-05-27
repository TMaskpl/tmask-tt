from celery import shared_task


@shared_task(name='transfers.execute')
def execute_transfer(job_id: int = None, scheduled_id: int = None, gpg_passphrase: str = None):
    pass  # Implemented in services/worker/tasks.py
