from django import forms
from apps.connections.models import Connection
from .models import DbTransferJob


class DbTransferForm(forms.ModelForm):
    SCOPE_WHOLE_DB = 'whole_db'
    SCOPE_TABLE = 'table'
    SCOPE_CHOICES = [(SCOPE_WHOLE_DB, 'CAŁA BAZA'), (SCOPE_TABLE, 'POJEDYNCZA TABELA')]

    ENGINE_CHOICES = [('postgres', 'POSTGRES'), ('mysql', 'MYSQL'), ('mssql', 'MSSQL')]

    engine = forms.ChoiceField(choices=ENGINE_CHOICES, widget=forms.RadioSelect, initial='postgres')
    scope = forms.ChoiceField(choices=SCOPE_CHOICES, widget=forms.RadioSelect, initial=SCOPE_WHOLE_DB)

    class Meta:
        model = DbTransferJob
        fields = ['engine', 'source_connection', 'table_name', 'dest_connection', 'verify_row_count']
        labels = {'verify_row_count': 'Weryfikuj liczbę wierszy po transferze (COUNT)'}

    def __init__(self, *args, user=None, engine=None, **kwargs):
        super().__init__(*args, **kwargs)
        selected_engine = engine or (self.data.get('engine') if self.is_bound else None) or 'postgres'
        qs = Connection.objects.filter(kind=selected_engine)
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
        src = cleaned.get('source_connection')
        dst = cleaned.get('dest_connection')
        if src and dst and src.kind != dst.kind:
            raise forms.ValidationError('Źródło i cel muszą być tym samym silnikiem bazy danych.')
        return cleaned

    def save(self, commit=True):
        job = super().save(commit=False)
        job.engine = self.cleaned_data['source_connection'].kind
        if commit:
            job.save()
        return job
