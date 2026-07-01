import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from apps.transfers.forms import TransferForm, _validate_source_filename
from apps.transfers.models import TransferJob
from django.core.exceptions import ValidationError


@pytest.mark.django_db
class TestTransferFormUpload:
    """The form accepts an uploaded file and derives source_path as
    /transfers/<filename> so the worker can resolve the volume-mounted path."""

    def _form(self, filename, user, conn, content=b'data', size=None):
        upload = SimpleUploadedFile(filename, content)
        if size is not None:
            upload.size = size
        return TransferForm(
            {'connection': conn.pk, 'destination_path': '/dst/'},
            {'upload': upload},
            user=user,
        )

    def test_valid_upload_derives_source_path(self, regular_user, make_connection):
        form = self._form('backup.tar', regular_user, make_connection(regular_user))
        assert form.is_valid(), form.errors
        assert form.cleaned_data['source_path'] == f'{settings.TRANSFERS_DIR}/backup.tar'

    def test_upload_over_limit_rejected(self, regular_user, make_connection):
        form = self._form('big.tar', regular_user, make_connection(regular_user),
                          size=settings.MAX_UPLOAD_BYTES + 1)
        assert not form.is_valid()
        assert 'upload' in form.errors

    def test_upload_at_limit_accepted(self, regular_user, make_connection):
        form = self._form('exact.tar', regular_user, make_connection(regular_user),
                          size=settings.MAX_UPLOAD_BYTES)
        assert form.is_valid(), form.errors

    def test_missing_upload_rejected(self, regular_user, make_connection):
        form = TransferForm(
            {'connection': make_connection(regular_user).pk, 'destination_path': '/dst/'},
            {},
            user=regular_user,
        )
        assert not form.is_valid()
        assert 'upload' in form.errors

    def test_upload_label_mentions_local(self, regular_user):
        form = TransferForm(user=regular_user)
        assert 'local' in form.fields['upload'].label.lower()


class TestValidateSourceFilename:
    def test_accepts_simple_filename(self):
        _validate_source_filename('backup.tar.gz')

    def test_accepts_filename_with_dots(self):
        _validate_source_filename('file.v2.tar.gz')

    def test_rejects_forward_slash(self):
        with pytest.raises(ValidationError):
            _validate_source_filename('path/file.tar')

    def test_rejects_backslash(self):
        with pytest.raises(ValidationError):
            _validate_source_filename('path\\file.tar')

    def test_rejects_leading_dash(self):
        with pytest.raises(ValidationError):
            _validate_source_filename('-flag')

    def test_rejects_control_characters(self):
        with pytest.raises(ValidationError):
            _validate_source_filename('file\x1fname')

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError):
            _validate_source_filename('')

    def test_rejects_single_dot(self):
        with pytest.raises(ValidationError):
            _validate_source_filename('.')

    def test_rejects_double_dot(self):
        with pytest.raises(ValidationError):
            _validate_source_filename('..')


@pytest.mark.django_db
class TestTransferCreateWithGPG:
    """GPG passphrase is wired through the form to Celery dispatch."""

    def _post(self, auth_client, conn, passphrase):
        return auth_client.post(reverse('transfers:create'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': SimpleUploadedFile('secret.tar', b'x'),
            'gpg_passphrase': passphrase,
        })

    def test_gpg_passphrase_passed_to_delay(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            self._post(auth_client, conn, 'mypassword123')
        job = TransferJob.objects.get(owner=regular_user)
        mock_delay.assert_called_once_with('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': 'mypassword123'})

    def test_empty_passphrase_passed_as_none(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            self._post(auth_client, conn, '')
        job = TransferJob.objects.get(owner=regular_user)
        mock_delay.assert_called_once_with('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': None})

    def test_whitespace_passphrase_treated_as_none(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            self._post(auth_client, conn, '   ')
        job = TransferJob.objects.get(owner=regular_user)
        mock_delay.assert_called_once_with('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': None})

    def test_source_path_stored_from_upload(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/remote/archive.tar.gz',
                'upload': SimpleUploadedFile('archive.tar.gz', b'x'),
            })
        job = TransferJob.objects.get(owner=regular_user)
        assert job.source_path == f'{tmp_path}/archive.tar.gz'
        mock_delay.assert_called_once()
