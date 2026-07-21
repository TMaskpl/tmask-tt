from django import forms
from .models import Connection, KIND_DB_KINDS


class ConnectionForm(forms.ModelForm):
    class Meta:
        model = Connection
        fields = [
            'name', 'kind', 'host', 'port', 'username', 'password', 'db_name', 'ssh_key',
            'ssh_key_passphrase',
            'protocol', 'compress', 'encrypt', 'strict_host_key_checking',
            'known_host_key', 'dry_run_before_transfer', 'verify_checksum',
        ]
        labels = {
            'dry_run_before_transfer': 'Dry-run przed transferem (tylko rsync)',
            'verify_checksum':         'Weryfikuj integralność SHA-256 po transferze',
            'db_name':                 'DB NAME (Postgres/MySQL/MSSQL)',
            'ssh_key_passphrase':      'Hasło klucza SSH (jeśli klucz jest zaszyfrowany)',
        }
        widgets = {
            'password': forms.PasswordInput(render_value=True),
            'ssh_key': forms.Textarea(attrs={'rows': 6}),
            'ssh_key_passphrase': forms.PasswordInput(render_value=True, attrs={'autocomplete': 'new-password'}),
            'known_host_key': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'hostname ssh-rsa AAAA... — kliknij [SCAN] aby pobrać automatycznie',
            }),
        }

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get('kind')
        if kind in KIND_DB_KINDS:
            if not cleaned.get('password'):
                raise forms.ValidationError('Podaj hasło do bazy danych.')
            if not cleaned.get('db_name'):
                raise forms.ValidationError('Podaj nazwę bazy danych (DB NAME).')
        else:
            if not cleaned.get('password') and not cleaned.get('ssh_key'):
                raise forms.ValidationError('Podaj hasło lub klucz SSH.')
        return cleaned

    def clean_dry_run_before_transfer(self):
        value = self.cleaned_data.get('dry_run_before_transfer')
        protocol = self.cleaned_data.get('protocol')
        if value and protocol != 'rsync':
            raise forms.ValidationError('Dry-run jest dostępny tylko dla protokołu rsync.')
        return value
