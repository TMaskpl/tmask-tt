import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('connections', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TransferJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_path', models.CharField(max_length=2000)),
                ('destination_path', models.CharField(max_length=2000)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'PENDING'),
                        ('running', 'RUNNING'),
                        ('done', 'DONE'),
                        ('failed', 'FAILED'),
                    ],
                    default='pending',
                    max_length=10,
                )),
                ('celery_task_id', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('owner', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='jobs',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('connection', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='jobs',
                    to='connections.connection',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TransferLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('level', models.CharField(
                    choices=[
                        ('info', 'INFO'),
                        ('warn', 'WARN'),
                        ('error', 'ERROR'),
                    ],
                    default='info',
                    max_length=5,
                )),
                ('message', models.TextField()),
                ('job', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='logs',
                    to='transfers.transferjob',
                )),
            ],
            options={
                'ordering': ['timestamp'],
            },
        ),
    ]
