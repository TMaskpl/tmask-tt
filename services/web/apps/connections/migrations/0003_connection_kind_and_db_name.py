from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('connections', '0002_dry_run_and_checksum'),
    ]

    operations = [
        migrations.AddField(
            model_name='connection',
            name='kind',
            field=models.CharField(choices=[('ssh', 'SSH'), ('postgres', 'Postgres')], default='ssh', max_length=10),
        ),
        migrations.AddField(
            model_name='connection',
            name='db_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
