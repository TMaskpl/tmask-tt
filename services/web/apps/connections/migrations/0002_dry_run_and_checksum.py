# Generated migration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('connections', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='connection',
            name='dry_run_before_transfer',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='connection',
            name='verify_checksum',
            field=models.BooleanField(default=False),
        ),
    ]
