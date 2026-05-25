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

    def test_user_has_notify_on_done_default_false(self, django_user_model):
        user = django_user_model.objects.create_user(
            username='notif_test', password='pass'
        )
        assert user.notify_on_done is False

    def test_user_has_notify_on_failed_default_true(self, django_user_model):
        user = django_user_model.objects.create_user(
            username='notif_test2', password='pass'
        )
        assert user.notify_on_failed is True

    def test_user_has_webhook_url_default_empty(self, django_user_model):
        user = django_user_model.objects.create_user(
            username='webhook_test', password='pass'
        )
        assert user.webhook_url == ''

    def test_user_has_webhook_on_done_default_false(self, django_user_model):
        user = django_user_model.objects.create_user(
            username='webhook_test2', password='pass'
        )
        assert user.webhook_on_done is False

    def test_user_has_webhook_on_failed_default_true(self, django_user_model):
        user = django_user_model.objects.create_user(
            username='webhook_test3', password='pass'
        )
        assert user.webhook_on_failed is True


@pytest.mark.django_db
class TestProfileForm:
    def test_form_has_required_fields(self):
        from apps.accounts.forms import ProfileForm
        form = ProfileForm()
        assert 'email' in form.fields
        assert 'notify_on_done' in form.fields
        assert 'notify_on_failed' in form.fields

    def test_form_includes_webhook_fields(self):
        from apps.accounts.forms import ProfileForm
        form = ProfileForm()
        assert 'webhook_url' in form.fields
        assert 'webhook_on_done' in form.fields
        assert 'webhook_on_failed' in form.fields

    def test_form_saves_email_and_prefs(self, django_user_model):
        from apps.accounts.forms import ProfileForm
        user = django_user_model.objects.create_user(username='ptest', password='p')
        form = ProfileForm(
            data={'email': 'user@example.com', 'notify_on_done': True, 'notify_on_failed': False},
            instance=user,
        )
        assert form.is_valid(), form.errors
        saved = form.save()
        assert saved.email == 'user@example.com'
        assert saved.notify_on_done is True
        assert saved.notify_on_failed is False
