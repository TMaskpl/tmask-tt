from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_notify_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="webhook_url",
            field=models.URLField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name="user",
            name="webhook_on_done",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="webhook_on_failed",
            field=models.BooleanField(default=True),
        ),
    ]
