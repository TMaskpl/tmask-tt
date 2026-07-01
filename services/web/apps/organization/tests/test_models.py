import pytest


@pytest.mark.django_db
class TestGetOrganization:
    def test_creates_default_organization_on_first_call(self):
        from apps.organization.models import Organization, get_organization
        assert Organization.objects.count() == 0
        org = get_organization()
        assert org.pk == 1
        assert org.name == 'Organizacja'
        assert Organization.objects.count() == 1

    def test_returns_same_row_on_subsequent_calls(self):
        from apps.organization.models import get_organization
        first = get_organization()
        first.name = 'Acme Corp'
        first.save()
        second = get_organization()
        assert second.pk == first.pk
        assert second.name == 'Acme Corp'


@pytest.mark.django_db
class TestOrganizationModel:
    def test_str_returns_name(self):
        from apps.organization.models import Organization
        org = Organization.objects.create(pk=1, name='Test Org')
        assert str(org) == 'Test Org'
