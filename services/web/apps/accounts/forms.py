from django import forms
from django.contrib.auth import get_user_model
from utils.url_validator import block_private_url


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)


class ProfileForm(forms.ModelForm):
    class Meta:
        model  = get_user_model()
        fields = [
            'email',
            'notify_on_done',
            'notify_on_failed',
            'webhook_url',
            'webhook_on_done',
            'webhook_on_failed',
            'telegram_chat_id',
            'telegram_on_done',
            'telegram_on_failed',
        ]
        labels = {
            'email':              'Adres email',
            'notify_on_done':     'Powiadamiaj o sukcesach transferu',
            'notify_on_failed':   'Powiadamiaj o błędach transferu',
            'webhook_url':        'Webhook URL (Slack)',
            'webhook_on_done':    'Webhook przy sukcesie transferu',
            'webhook_on_failed':  'Webhook przy błędzie transferu',
            'telegram_chat_id':   'Telegram Chat ID',
            'telegram_on_done':   'Telegram przy sukcesie transferu',
            'telegram_on_failed': 'Telegram przy błędzie transferu',
        }

    def clean_webhook_url(self):
        url = self.cleaned_data.get('webhook_url', '').strip()
        if url:
            try:
                block_private_url(url)
            except ValueError as e:
                raise forms.ValidationError(str(e))
        return url
