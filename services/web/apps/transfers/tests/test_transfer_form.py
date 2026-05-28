import pytest
from django.urls import reverse
from apps.transfers.forms import TransferForm, _validate_source_filename, TRANSFERS_MOUNT
from apps.transfers.models import TransferJob, STATUS_PENDING
from django.core.exceptions import ValidationError


@pytest.mark.django_db
class TestTransferFormSourcePath:
    """Regression tests for filename-only source_path field.

    The form accepts only a bare filename (e.g. 'file.tar') and auto-prepends
    /transfers/ so the worker container can resolve the volume-mounted path.
    """

    def _form(self, source_path, user, conn):
        return TransferForm(
            {'source_path': source_path, 'connection': conn.pk, 'destination_path': '/dst/'},
            user=user,
        )

    def test_filename_prepends_transfers_mount(self, regular_user, make_connection):
        form = self._form('dn-gpg.txt', regular_user, make_connection(regular_user))
        assert form.is_valid(), form.errors
        assert form.cleaned_data['source_path'] == f'{TRANSFERS_MOUNT}/dn-gpg.txt'

    def test_filename_with_whitespace_stripped(self, regular_user, make_connection):
        form = self._form('  file.tar  ', regular_user, make_connection(regular_user))
        assert form.is_valid(), form.errors
        assert form.cleaned_data['source_path'] == f'{TRANSFERS_MOUNT}/file.tar'

    def test_existing_transfers_prefix_not_doubled(self, regular_user, make_connection):
        """User may paste /transfers/file.tar — should not become /transfers//transfers/file.tar."""
        form = self._form('/transfers/file.tar', regular_user, make_connection(regular_user))
        assert form.is_valid(), form.errors
        assert form.cleaned_data['source_path'] == f'{TRANSFERS_MOUNT}/file.tar'

    def test_rejects_path_with_forward_slash(self, regular_user, make_connection):
        form = self._form('/data/file.tar', regular_user, make_connection(regular_user))
        assert not form.is_valid()
        assert 'source_path' in form.errors

    def test_rejects_path_with_backslash(self, regular_user, make_connection):
        form = self._form('data\\file.tar', regular_user, make_connection(regular_user))
        assert not form.is_valid()
        assert 'source_path' in form.errors

    def test_rejects_leading_dash(self, regular_user, make_connection):
        form = self._form('-rf file.tar', regular_user, make_connection(regular_user))
        assert not form.is_valid()
        assert 'source_path' in form.errors

    def test_rejects_control_characters(self, regular_user, make_connection):
        form = self._form('file\x00.tar', regular_user, make_connection(regular_user))
        assert not form.is_valid()
        assert 'source_path' in form.errors

    def test_widget_has_placeholder(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        form = TransferForm(user=regular_user)
        widget_attrs = form.fields['source_path'].widget.attrs
        assert 'placeholder' in widget_attrs

    def test_source_path_label_is_local_transfers(self, regular_user):
        form = TransferForm(user=regular_user)
        assert 'transfers' in form.fields['source_path'].label.lower()


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


@pytest.mark.django_db
class TestTransferCreateWithGPG:
    """Tests verifying GPG passphrase is wired through the form to Celery dispatch."""

    def test_gpg_passphrase_passed_to_delay(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks):
        mock_delay = mocker.patch('apps.transfers.views.execute_transfer.delay')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'source_path': 'secret.tar',
                'destination_path': '/backup/',
                'gpg_passphrase': 'mypassword123',
            })
        job = TransferJob.objects.get(owner=regular_user)
        mock_delay.assert_called_once_with(job_id=job.pk, gpg_passphrase='mypassword123')

    def test_empty_passphrase_passed_as_none(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks):
        mock_delay = mocker.patch('apps.transfers.views.execute_transfer.delay')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'source_path': 'file.tar',
                'destination_path': '/backup/',
                'gpg_passphrase': '',
            })
        job = TransferJob.objects.get(owner=regular_user)
        mock_delay.assert_called_once_with(job_id=job.pk, gpg_passphrase=None)

    def test_whitespace_passphrase_treated_as_none(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks):
        mock_delay = mocker.patch('apps.transfers.views.execute_transfer.delay')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'source_path': 'file.tar',
                'destination_path': '/backup/',
                'gpg_passphrase': '   ',
            })
        job = TransferJob.objects.get(owner=regular_user)
        mock_delay.assert_called_once_with(job_id=job.pk, gpg_passphrase=None)

    def test_source_path_stored_with_transfers_prefix(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks):
        mock_delay = mocker.patch('apps.transfers.views.execute_transfer.delay')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'source_path': 'archive.tar.gz',
                'destination_path': '/remote/archive.tar.gz',
            })
        job = TransferJob.objects.get(owner=regular_user)
        assert job.source_path == f'{TRANSFERS_MOUNT}/archive.tar.gz'
        mock_delay.assert_called_once()
