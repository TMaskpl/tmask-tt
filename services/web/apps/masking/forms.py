from django import forms
from apps.connections.models import Connection, KIND_DB_KINDS
from .models import MaskingRule


class MaskingRuleForm(forms.ModelForm):
    class Meta:
        model = MaskingRule
        fields = ['connection', 'table_name', 'column_name', 'faker_provider']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['connection'].queryset = Connection.objects.filter(kind__in=KIND_DB_KINDS)
