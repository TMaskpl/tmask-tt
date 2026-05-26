from django import forms

from apps.connections.models import Connection
from apps.flows.models import Flow
from apps.transfers.forms import _validate_transfer_path
from .models import ScheduledTransfer


class ScheduledTransferForm(forms.ModelForm):
    class Meta:
        model = ScheduledTransfer
        fields = ['connection', 'flow', 'source_path', 'destination_path', 'cron_expr', 'enabled']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['connection'].required = False
        self.fields['flow'].required = False
        self.fields['source_path'].required = False
        self.fields['destination_path'].required = False
        if user:
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)
            self.fields['flow'].queryset = Flow.objects.filter(owner=user)

    def clean(self):
        cleaned = super().clean()
        conn = cleaned.get('connection')
        flow = cleaned.get('flow')
        if conn and flow:
            raise forms.ValidationError('Set connection or flow, not both.')
        if not conn and not flow:
            raise forms.ValidationError('Set either connection or flow.')
        if flow:
            cleaned['source_path'] = ''
            cleaned['destination_path'] = ''
        else:
            if not cleaned.get('source_path'):
                self.add_error('source_path', 'Required when using a connection.')
            if not cleaned.get('destination_path'):
                self.add_error('destination_path', 'Required when using a connection.')
        return cleaned

    def clean_source_path(self):
        value = self.cleaned_data.get('source_path', '')
        if value:
            _validate_transfer_path(value)
        return value

    def clean_destination_path(self):
        value = self.cleaned_data.get('destination_path', '')
        if value:
            _validate_transfer_path(value)
        return value

    def clean_cron_expr(self):
        expr = self.cleaned_data['cron_expr']
        parts = expr.split()
        if len(parts) != 5:
            raise forms.ValidationError('INVALID CRON — format: "min hour day month weekday" (5 fields)')
        return expr
