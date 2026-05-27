import re

from django import forms
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


class TransferForm(forms.ModelForm):
    gpg_passphrase = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off'}),
        label='GPG Passphrase',
    )

    class Meta:
        model = TransferJob
        fields = ['source_path', 'connection', 'destination_path']
        labels = {
            'source_path': 'Local ./transfers',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)

    def clean_source_path(self):
        value = self.cleaned_data['source_path']
        _validate_transfer_path(value)
        return value

    def clean_destination_path(self):
        value = self.cleaned_data['destination_path']
        _validate_transfer_path(value)
        return value
