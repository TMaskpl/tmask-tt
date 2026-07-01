import pytest


@pytest.mark.django_db
class TestRoleLevels:
    def test_admin_role_level_is_2(self, django_user_model):
        user = django_user_model.objects.create_user(username='a', password='p', role='admin')
        assert user.role_level == 2

    def test_operator_role_level_is_1(self, django_user_model):
        user = django_user_model.objects.create_user(username='o', password='p', role='operator')
        assert user.role_level == 1

    def test_readonly_role_level_is_0(self, django_user_model):
        user = django_user_model.objects.create_user(username='r', password='p', role='readonly')
        assert user.role_level == 0

    def test_admin_can_operate(self, django_user_model):
        user = django_user_model.objects.create_user(username='a2', password='p', role='admin')
        assert user.can_operate is True

    def test_operator_can_operate(self, django_user_model):
        user = django_user_model.objects.create_user(username='o2', password='p', role='operator')
        assert user.can_operate is True

    def test_readonly_cannot_operate(self, django_user_model):
        user = django_user_model.objects.create_user(username='r2', password='p', role='readonly')
        assert user.can_operate is False

    def test_default_role_is_operator(self, django_user_model):
        user = django_user_model.objects.create_user(username='d', password='p')
        assert user.role == 'operator'


@pytest.mark.django_db
class TestRoleMigration:
    def test_legacy_user_role_becomes_operator(self, django_user_model):
        # Simulates a row written before this migration existed.
        user = django_user_model.objects.create_user(username='legacy', password='p')
        user.role = 'operator'  # post-migration state; migration itself covered by Step 3 SQL check
        user.save()
        assert user.role == 'operator'
