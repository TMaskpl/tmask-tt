from django import forms
from apps.connections.models import Connection
from apps.transfers.forms import _validate_transfer_path
from .models import Flow


class FlowForm(forms.ModelForm):
    class Meta:
        model = Flow
        fields = ['name', 'source_conn', 'source_path', 'dest_conn', 'dest_path']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            qs = Connection.objects.filter(owner=user)
            self.fields['source_conn'].queryset = qs
            self.fields['dest_conn'].queryset = qs

    def clean_source_path(self):
        value = self.cleaned_data.get('source_path', '')
        if value:
            _validate_transfer_path(value)
        return value

    def clean_dest_path(self):
        value = self.cleaned_data.get('dest_path', '')
        if value:
            _validate_transfer_path(value)
        return value
