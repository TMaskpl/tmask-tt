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


class TransferForm(forms.ModelForm):
    upload = forms.FileField(
        label='Local file',
        widget=forms.ClearableFileInput(attrs={'data-file-display': 'upload-file-name'}),
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
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)

    def clean_upload(self):
        uploaded = self.cleaned_data['upload']
        if uploaded.size > settings.MAX_UPLOAD_BYTES:
            raise ValidationError('Plik przekracza limit 100 MB.')
        _validate_source_filename(uploaded.name)
        return uploaded

    def clean(self):
        cleaned = super().clean()
        uploaded = cleaned.get('upload')
        if uploaded is not None:
            cleaned['source_path'] = f'{settings.TRANSFERS_DIR}/{uploaded.name}'
        return cleaned

    def clean_destination_path(self):
        value = self.cleaned_data['destination_path']
        _validate_transfer_path(value)
        return value
