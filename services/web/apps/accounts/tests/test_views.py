import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestLoginView:
    def test_login_page_renders(self, client):
        url = reverse('accounts:login')
        response = client.get(url)
        assert response.status_code == 200

    def test_login_with_valid_credentials(self, client, regular_user):
        url = reverse('accounts:login')
        response = client.post(url, {'username': 'user_test', 'password': 'testpass123'})
        assert response.status_code == 302

    def test_login_with_invalid_credentials(self, client):
        url = reverse('accounts:login')
        response = client.post(url, {'username': 'wrong', 'password': 'wrong'})
        assert response.status_code == 200
        assert '__all__' in response.context['form'].errors

    def test_logout_redirects_to_login(self, auth_client):
        url = reverse('accounts:logout')
        response = auth_client.post(url)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_unauthenticated_access_to_users_requires_login(self, client):
        url = reverse('accounts:users')
        response = client.get(url)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_regular_user_cannot_access_users_list(self, auth_client):
        url = reverse('accounts:users')
        response = auth_client.get(url)
        assert response.status_code == 403


@pytest.mark.django_db
class TestProfileView:
    def test_unauthenticated_redirects_to_login(self, client):
        url = reverse('accounts:profile')
        response = client.get(url)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_get_renders_form_with_current_values(self, auth_client, regular_user):
        regular_user.email = 'existing@example.com'
        regular_user.save()
        url = reverse('accounts:profile')
        response = auth_client.get(url)
        assert response.status_code == 200
        assert response.context['form'].instance.email == 'existing@example.com'

    def test_post_saves_prefs_and_redirects(self, auth_client, regular_user):
        url = reverse('accounts:profile')
        response = auth_client.post(url, {
            'email': 'updated@example.com',
            'notify_on_done': True,
            'notify_on_failed': False,
        })
        assert response.status_code == 302
        regular_user.refresh_from_db()
        assert regular_user.email == 'updated@example.com'
        assert regular_user.notify_on_done is True
        assert regular_user.notify_on_failed is False

    def test_post_with_invalid_email_shows_errors(self, auth_client):
        url = reverse('accounts:profile')
        response = auth_client.post(url, {
            'email': 'not-an-email',
            'notify_on_done': False,
            'notify_on_failed': True,
        })
        assert response.status_code == 200
        assert 'email' in response.context['form'].errors
