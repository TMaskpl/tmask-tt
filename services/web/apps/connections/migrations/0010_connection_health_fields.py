from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('connections', '0009_connection_kind_mysql_mssql'),
    ]

    operations = [
        migrations.AddField(
            model_name='connection',
            name='health_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='connection',
            name='health_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='connection',
            name='health_status',
            field=models.CharField(choices=[('unknown', 'Unknown'), ('ok', 'OK'), ('failed', 'Failed')], default='unknown', max_length=10),
        ),
    ]
