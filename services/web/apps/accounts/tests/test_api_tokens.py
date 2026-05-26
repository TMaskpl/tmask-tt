import pytest
from django.urls import reverse
from apps.api.models import ApiToken, MAX_TOKENS_PER_USER


@pytest.mark.django_db
class TestGenerateApiToken:
    def test_generate_creates_token_and_stores_key_in_session(self, auth_client, regular_user):
        url = reverse('accounts:generate_api_token')
        response = auth_client.post(url, {'label': 'CI Jenkins'})
        assert response.status_code == 302
        assert ApiToken.objects.filter(user=regular_user, label='CI Jenkins').exists()
        assert 'new_api_token' in auth_client.session

    def test_raw_key_shown_in_session_is_64_chars(self, auth_client, regular_user):
        url = reverse('accounts:generate_api_token')
        auth_client.post(url, {'label': 'CI Jenkins'})
        raw_key = auth_client.session['new_api_token']
        assert len(raw_key) == 64

    def test_session_key_matches_stored_hash(self, auth_client, regular_user):
        import hashlib
        url = reverse('accounts:generate_api_token')
        auth_client.post(url, {'label': 'CI Jenkins'})
        raw_key = auth_client.session['new_api_token']
        token = ApiToken.objects.get(user=regular_user)
        assert token.key_hash == hashlib.sha256(raw_key.encode()).hexdigest()

    def test_empty_label_redirects_with_error_no_token_created(self, auth_client, regular_user):
        url = reverse('accounts:generate_api_token')
        response = auth_client.post(url, {'label': ''})
        assert response.status_code == 302
        assert not ApiToken.objects.filter(user=regular_user).exists()

    def test_limit_5_tokens_blocks_generation(self, auth_client, regular_user):
        for i in range(MAX_TOKENS_PER_USER):
            ApiToken.generate(regular_user, f'Token {i}')
        url = reverse('accounts:generate_api_token')
        response = auth_client.post(url, {'label': 'Extra'})
        assert response.status_code == 302
        assert ApiToken.objects.filter(user=regular_user).count() == MAX_TOKENS_PER_USER

    def test_unauthenticated_redirects_to_login(self, client):
        url = reverse('accounts:generate_api_token')
        response = client.post(url, {'label': 'Test'})
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_profile_shows_token_modal_with_key(self, auth_client, regular_user):
        gen_url = reverse('accounts:generate_api_token')
        auth_client.post(gen_url, {'label': 'CI Jenkins'})
        profile_url = reverse('accounts:profile')
        response = auth_client.get(profile_url)
        assert response.status_code == 200
        assert b'NOWY TOKEN API' in response.content

    def test_profile_modal_consumed_on_second_visit(self, auth_client, regular_user):
        gen_url = reverse('accounts:generate_api_token')
        auth_client.post(gen_url, {'label': 'CI Jenkins'})
        profile_url = reverse('accounts:profile')
        auth_client.get(profile_url)  # konsumuje sesję
        response = auth_client.get(profile_url)  # drugi visit — modal nie powinien być
        assert b'NOWY TOKEN API' not in response.content
