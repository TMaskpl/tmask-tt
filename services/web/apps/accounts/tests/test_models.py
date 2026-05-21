import pytest


@pytest.mark.django_db
class TestUser:
    def test_user_has_role_field(self, django_user_model):
        user = django_user_model.objects.create_user(
            username='tester', password='pass', role='user'
        )
        assert user.role == 'user'

    def test_admin_role(self, django_user_model):
        admin = django_user_model.objects.create_user(
            username='adm', password='pass', role='admin'
        )
        assert admin.is_admin is True

    def test_user_role_is_not_admin(self, django_user_model):
        user = django_user_model.objects.create_user(
            username='usr', password='pass', role='user'
        )
        assert user.is_admin is False
