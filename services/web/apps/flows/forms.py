from django import forms
from apps.connections.models import Connection
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
