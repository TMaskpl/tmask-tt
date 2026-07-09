from django import forms
from apps.connections.models import Connection, KIND_POSTGRES
from .models import PgTransferJob


class PgTransferForm(forms.ModelForm):
    SCOPE_WHOLE_DB = 'whole_db'
    SCOPE_TABLE = 'table'
    SCOPE_CHOICES = [(SCOPE_WHOLE_DB, 'CAŁA BAZA'), (SCOPE_TABLE, 'POJEDYNCZA TABELA')]

    scope = forms.ChoiceField(choices=SCOPE_CHOICES, widget=forms.RadioSelect, initial=SCOPE_WHOLE_DB)

    class Meta:
        model = PgTransferJob
        fields = ['source_connection', 'table_name', 'dest_connection', 'verify_row_count']
        labels = {'verify_row_count': 'Weryfikuj liczbę wierszy po transferze (COUNT)'}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Connection.objects.filter(kind=KIND_POSTGRES)
        self.fields['source_connection'].queryset = qs
        self.fields['dest_connection'].queryset = qs

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get('scope')
        table_name = (cleaned.get('table_name') or '').strip()
        if scope == self.SCOPE_TABLE and not table_name:
            raise forms.ValidationError('Wybierz tabelę dla trybu POJEDYNCZA TABELA.')
        if scope == self.SCOPE_WHOLE_DB:
            cleaned['table_name'] = ''
        return cleaned
