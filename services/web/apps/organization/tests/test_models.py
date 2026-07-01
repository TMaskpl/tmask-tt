import pytest


@pytest.mark.django_db
class TestGetOrganization:
    def test_migration_creates_the_default_row(self):
        from apps.organization.models import Organization
        org = Organization.objects.get(pk=1)
        assert org.name == 'Organizacja'

    def test_get_organization_is_idempotent(self):
        from apps.organization.models import Organization, get_organization
        count_before = Organization.objects.count()
        org = get_organization()
        assert org.pk == 1
        assert Organization.objects.count() == count_before

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
        org = Organization.objects.create(name='Test Org')
        assert str(org) == 'Test Org'
