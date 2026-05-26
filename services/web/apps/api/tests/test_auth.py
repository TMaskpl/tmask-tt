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
