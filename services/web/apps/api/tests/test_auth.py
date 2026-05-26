import hashlib
import pytest
from apps.api.models import ApiToken, MAX_TOKENS_PER_USER


@pytest.mark.django_db
class TestApiTokenModel:
    def test_generate_returns_token_and_raw_key(self, regular_user):
        token, raw_key = ApiToken.generate(regular_user, 'CI Jenkins')
        assert token.pk is not None
        assert token.user == regular_user
        assert token.label == 'CI Jenkins'
        assert len(raw_key) == 64
        assert token.key_hash == hashlib.sha256(raw_key.encode()).hexdigest()
        assert token.last_used_at is None

    def test_raw_key_not_stored_in_db(self, regular_user):
        token, raw_key = ApiToken.generate(regular_user, 'Test')
        assert token.key_hash != raw_key

    def test_max_tokens_constant_is_five(self):
        assert MAX_TOKENS_PER_USER == 5

    def test_ordering_newest_first(self, regular_user):
        t1, _ = ApiToken.generate(regular_user, 'First')
        t2, _ = ApiToken.generate(regular_user, 'Second')
        tokens = list(ApiToken.objects.filter(user=regular_user))
        assert tokens[0] == t2
        assert tokens[1] == t1


import json
from django.test import RequestFactory
from django.http import JsonResponse
from apps.api.auth import require_api_token, get_user_from_token


@pytest.mark.django_db
class TestRequireApiToken:
    def test_valid_token_sets_api_user(self, rf, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        request = rf.get('/', HTTP_AUTHORIZATION=f'Token {raw_key}')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({'user': request.api_user.pk})

        response = dummy_view(request)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['user'] == regular_user.pk

    def test_valid_token_updates_last_used_at(self, rf, regular_user, make_api_token):
        token, raw_key = make_api_token(regular_user)
        assert token.last_used_at is None
        request = rf.get('/', HTTP_AUTHORIZATION=f'Token {raw_key}')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({})

        dummy_view(request)
        token.refresh_from_db()
        assert token.last_used_at is not None

    def test_missing_header_returns_403(self, rf, regular_user):
        request = rf.get('/')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({})

        response = dummy_view(request)
        assert response.status_code == 403
        assert json.loads(response.content)['error'] == 'Invalid or missing token'

    def test_wrong_token_returns_403(self, rf, regular_user):
        request = rf.get('/', HTTP_AUTHORIZATION='Token wrongkey123')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({})

        response = dummy_view(request)
        assert response.status_code == 403

    def test_malformed_header_returns_403(self, rf, regular_user):
        request = rf.get('/', HTTP_AUTHORIZATION='Bearer sometoken')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({})

        response = dummy_view(request)
        assert response.status_code == 403
