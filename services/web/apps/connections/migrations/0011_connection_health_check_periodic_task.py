from django.db import migrations


def create_health_check_task(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=1, period='hours'
        )
        PeriodicTask.objects.get_or_create(
            name='connection-health-check',
            defaults={
                'interval': schedule,
                'task': 'connections.health_check_all',
                'enabled': True,
            }
        )
    except Exception:  # nosec B110 — django_celery_beat tables may not exist yet on first migrate
        pass


def remove_health_check_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='connection-health-check').delete()
    except Exception:  # nosec B110 — safe: only deletes if table exists
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('connections', '0010_connection_health_fields'),
        ('django_celery_beat', '0001_initial'),
    ]
    operations = [migrations.RunPython(create_health_check_task, remove_health_check_task)]
