from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0002_scheduledtransfer_flow_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='scheduledtransfer',
            name='connection',
        ),
        migrations.RemoveField(
            model_name='scheduledtransfer',
            name='source_path',
        ),
        migrations.RemoveField(
            model_name='scheduledtransfer',
            name='destination_path',
        ),
    ]
