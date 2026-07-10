from django import forms
from apps.connections.models import Connection, KIND_SSH
from apps.transfers.forms import _validate_transfer_path
from .models import Flow


class FlowForm(forms.ModelForm):
    class Meta:
        model = Flow
        fields = ['name', 'source_conn', 'source_path', 'dest_conn', 'dest_path', 'verify_checksum']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            # Flow is an SSH/SFTP relay mechanism (source_path/dest_path are
            # file paths) — Postgres connections can't be used here, they
            # belong to db_transfers. Filter them out so the dropdown can't
            # offer a choice that would only fail later, at run time.
            qs = Connection.objects.filter(kind=KIND_SSH)
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
