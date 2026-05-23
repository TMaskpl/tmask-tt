from django import forms
from .models import TransferJob
from apps.connections.models import Connection


class TransferForm(forms.ModelForm):
    gpg_passphrase = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off'}),
        label='GPG Passphrase',
    )

    class Meta:
        model = TransferJob
        fields = ['connection', 'source_path', 'destination_path']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)
