import importlib

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
    def test_migrate_user_role_to_operator_rewrites_legacy_rows(self, django_user_model):
        migration_module = importlib.import_module(
            'apps.accounts.migrations.0005_role_operator_readonly'
        )
        user = django_user_model.objects.create_user(username='legacy', password='p')
        django_user_model.objects.filter(pk=user.pk).update(role='user')
        from django.apps import apps as global_apps
        migration_module.migrate_user_role_to_operator(global_apps, None)
        user.refresh_from_db()
        assert user.role == 'operator'

    def test_migrate_user_role_to_operator_leaves_other_roles_untouched(self, django_user_model):
        migration_module = importlib.import_module(
            'apps.accounts.migrations.0005_role_operator_readonly'
        )
        admin = django_user_model.objects.create_user(username='stays_admin', password='p', role='admin')
        from django.apps import apps as global_apps
        migration_module.migrate_user_role_to_operator(global_apps, None)
        admin.refresh_from_db()
        assert admin.role == 'admin'
