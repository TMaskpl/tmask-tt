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
