import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('connections', '0003_connection_kind_and_db_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PgTransferJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('table_name', models.CharField(blank=True, max_length=255)),
                ('verify_row_count', models.BooleanField(default=False)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'PENDING'), ('running', 'RUNNING'), ('done', 'DONE'),
                        ('failed', 'FAILED'), ('cancelled', 'CANCELLED'),
                    ],
                    default='pending', max_length=10,
                )),
                ('celery_task_id', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pg_jobs', to=settings.AUTH_USER_MODEL)),
                ('source_connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pg_source_jobs', to='connections.connection')),
                ('dest_connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pg_dest_jobs', to='connections.connection')),
                ('cancelled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cancelled_pg_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='PgTransferLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('level', models.CharField(choices=[('info', 'INFO'), ('warn', 'WARN'), ('error', 'ERROR')], default='info', max_length=5)),
                ('message', models.TextField()),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='db_transfers.pgtransferjob')),
            ],
            options={'ordering': ['timestamp']},
        ),
    ]
