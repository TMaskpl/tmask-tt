from django import forms
from .models import Connection

class ConnectionForm(forms.ModelForm):
    class Meta:
        model = Connection
        fields = ['name', 'host', 'port', 'username', 'password', 'ssh_key',
                  'protocol', 'compress', 'encrypt', 'strict_host_key_checking']
        widgets = {
            'password': forms.PasswordInput(render_value=True),
            'ssh_key': forms.Textarea(attrs={'rows': 6}),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('password') and not cleaned.get('ssh_key'):
            raise forms.ValidationError('Podaj hasło lub klucz SSH.')
        return cleaned
