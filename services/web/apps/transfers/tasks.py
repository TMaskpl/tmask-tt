from celery import shared_task


@shared_task(name='transfers.execute')
def execute_transfer(job_id: int):
    pass  # Implemented in services/worker/tasks.py
