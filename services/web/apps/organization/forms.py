from django import forms
from .models import Organization


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name']
        labels = {'name': 'Nazwa organizacji'}
