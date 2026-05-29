from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_webhook_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="telegram_chat_id",
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.AddField(
            model_name="user",
            name="telegram_on_done",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="telegram_on_failed",
            field=models.BooleanField(default=True),
        ),
    ]
