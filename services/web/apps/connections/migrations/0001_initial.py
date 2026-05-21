import django.db.models.deletion
import django.utils.timezone
import encrypted_model_fields.fields
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Connection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('host', models.CharField(max_length=255)),
                ('port', models.IntegerField(default=22)),
                ('username', models.CharField(max_length=100)),
                ('password', encrypted_model_fields.fields.EncryptedCharField(blank=True, max_length=500, null=True)),
                ('ssh_key', encrypted_model_fields.fields.EncryptedTextField(blank=True, null=True)),
                ('protocol', models.CharField(
                    choices=[('sftp', 'SFTP/SCP'), ('rsync', 'rsync')],
                    default='sftp',
                    max_length=10,
                )),
                ('compress', models.BooleanField(default=False)),
                ('encrypt', models.BooleanField(default=False)),
                ('strict_host_key_checking', models.BooleanField(default=True)),
                ('known_host_key', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('owner', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='connections',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
