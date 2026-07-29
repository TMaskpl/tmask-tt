import pytest
from modules.masking.faker_engine import mask_value, PROVIDERS


class TestMaskValue:
    def test_provider_keys_match_django_model_choices(self):
        # Global Constraint: kluczowa spójność między web (Task 1) i worker (ten task)
        from apps.masking.models import FAKER_PROVIDER_KEYS
        assert set(PROVIDERS.keys()) == set(FAKER_PROVIDER_KEYS)

    def test_generates_non_empty_string_for_each_provider(self):
        for provider in PROVIDERS:
            result = mask_value(provider)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_truncates_to_max_length(self):
        result = mask_value('street_address', max_length=5)
        assert len(result) <= 5

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            mask_value('not_a_real_provider')
