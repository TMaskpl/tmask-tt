import re

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from .models import TransferJob
from apps.connections.models import Connection


def _validate_transfer_path(value: str) -> None:
    if value.startswith('-'):
        raise ValidationError('Ścieżka nie może zaczynać się od "-".')
    if re.search(r'[\x00-\x1f]', value):
        raise ValidationError('Ścieżka zawiera niedozwolone znaki kontrolne.')
    if '..' in value.replace('\\', '/').split('/'):
        raise ValidationError('Ścieżka nie może zawierać sekwencji "..".')


def _validate_source_filename(value: str) -> None:
    if value in ('', '.', '..'):
        raise ValidationError('Nieprawidłowa nazwa pliku.')
    if '/' in value or '\\' in value:
        raise ValidationError('Podaj tylko nazwę pliku bez ścieżki, np. plik.tar.gz')
    if value.startswith('-'):
        raise ValidationError('Nazwa pliku nie może zaczynać się od "-".')
    if re.search(r'[\x00-\x1f]', value):
        raise ValidationError('Nazwa pliku zawiera niedozwolone znaki kontrolne.')


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Cleans each selected file individually (size/name validators still
    apply per-file) and always returns a list, even for a single file —
    the batch-upload code path relies on that to distinguish 1 vs N files
    without special-casing the non-list shape everywhere."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if not isinstance(data, (list, tuple)):
            return [single_file_clean(data, initial)]
        if not data:
            if self.required:
                raise ValidationError(self.error_messages['required'], code='required')
            return []
        return [single_file_clean(d, initial) for d in data]


class TransferForm(forms.ModelForm):
    upload = MultipleFileField(
        label='Local file(s)',
        widget=MultipleFileInput(attrs={'multiple': True, 'data-file-display': 'upload-file-name'}),
    )
    gpg_passphrase = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off'}),
        label='GPG Passphrase',
    )

    class Meta:
        model = TransferJob
        fields = ['connection', 'destination_path']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['connection'].queryset = Connection.objects.all()

    def clean_upload(self):
        uploads = self.cleaned_data['upload']
        for uploaded in uploads:
            if uploaded.size > settings.MAX_UPLOAD_BYTES:
                raise ValidationError(f'Plik {uploaded.name} przekracza limit 100 MB.')
            _validate_source_filename(uploaded.name)
        return uploads

    def clean(self):
        cleaned = super().clean()
        uploads = cleaned.get('upload')
        dest = cleaned.get('destination_path')
        if uploads:
            if len(uploads) == 1:
                cleaned['source_path'] = f'{settings.TRANSFERS_DIR}/{uploads[0].name}'
            elif dest and not dest.endswith('/'):
                raise ValidationError(
                    'Przy wielu plikach docelowa ścieżka musi być katalogiem (zakończonym "/").'
                )
        return cleaned

    def clean_destination_path(self):
        value = self.cleaned_data['destination_path']
        _validate_transfer_path(value)
        return value
