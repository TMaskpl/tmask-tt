from django.db import migrations


def create_cleanup_task(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=5, period='minutes'
        )
        PeriodicTask.objects.get_or_create(
            name='cleanup-orphan-jobs',
            defaults={
                'interval': schedule,
                'task': 'transfers.cleanup_orphans',
                'enabled': True,
            }
        )
    except Exception:
        pass  # django_celery_beat tables may not exist yet on first migrate


def remove_cleanup_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='cleanup-orphan-jobs').delete()
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('transfers', '0001_initial'),
        ('django_celery_beat', '0001_initial'),
    ]
    operations = [migrations.RunPython(create_cleanup_task, remove_cleanup_task)]
