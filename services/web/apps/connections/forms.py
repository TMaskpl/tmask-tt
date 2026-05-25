from django import forms
from .models import Connection

class ConnectionForm(forms.ModelForm):
    class Meta:
        model = Connection
        fields = ['name', 'host', 'port', 'username', 'password', 'ssh_key',
                  'protocol', 'compress', 'encrypt', 'strict_host_key_checking', 'known_host_key']
        widgets = {
            'password': forms.PasswordInput(render_value=True),
            'ssh_key': forms.Textarea(attrs={'rows': 6}),
            'known_host_key': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'hostname ssh-rsa AAAA... — kliknij [SCAN] aby pobrać automatycznie',
            }),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('password') and not cleaned.get('ssh_key'):
            raise forms.ValidationError('Podaj hasło lub klucz SSH.')
        return cleaned
