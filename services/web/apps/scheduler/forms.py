from django import forms

from apps.connections.models import Connection
from .models import ScheduledTransfer


class ScheduledTransferForm(forms.ModelForm):
    class Meta:
        model = ScheduledTransfer
        fields = ['connection', 'source_path', 'destination_path', 'cron_expr', 'enabled']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)

    def clean_cron_expr(self):
        expr = self.cleaned_data['cron_expr']
        parts = expr.split()
        if len(parts) != 5:
            raise forms.ValidationError('INVALID CRON — format: "min hour day month weekday" (5 fields)')
        return expr
