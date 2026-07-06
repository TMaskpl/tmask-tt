from django.db import migrations


def create_retention_task(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=1, period='hours'
        )
        PeriodicTask.objects.get_or_create(
            name='cleanup-old-transfers',
            defaults={
                'interval': schedule,
                'task': 'transfers.cleanup_old_transfers',
                'enabled': True,
            }
        )
    except Exception:  # nosec B110 — django_celery_beat tables may not exist yet on first migrate
        pass


def remove_retention_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='cleanup-old-transfers').delete()
    except Exception:  # nosec B110 — safe: only deletes if table exists
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('transfers', '0004_transferjob_cancelled_status'),
        ('django_celery_beat', '0001_initial'),
    ]
    operations = [migrations.RunPython(create_retention_task, remove_retention_task)]
