from django.conf import settings


def test_transfers_dir_setting():
    assert settings.TRANSFERS_DIR == '/transfers'


def test_max_upload_bytes_is_100mb():
    assert settings.MAX_UPLOAD_BYTES == 100 * 1024 * 1024


def test_transfers_retention_days_default():
    assert settings.TRANSFERS_RETENTION_DAYS == 1
