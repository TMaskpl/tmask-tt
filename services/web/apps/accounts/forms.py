from django import forms
from django.contrib.auth import get_user_model


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)


class ProfileForm(forms.ModelForm):
    class Meta:
        model  = get_user_model()
        fields = ['email', 'notify_on_done', 'notify_on_failed']
        labels = {
            'email':            'Adres email',
            'notify_on_done':   'Powiadamiaj o sukcesach transferu',
            'notify_on_failed': 'Powiadamiaj o błędach transferu',
        }
