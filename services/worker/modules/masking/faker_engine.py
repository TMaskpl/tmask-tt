from faker import Faker

_fake = Faker()

PROVIDERS = {
    'first_name': _fake.first_name,
    'last_name': _fake.last_name,
    'name': _fake.name,
    'email': _fake.email,
    'phone_number': _fake.phone_number,
    'street_address': _fake.street_address,
    'city': _fake.city,
    'postcode': _fake.postcode,
    'country': _fake.country,
    'company': _fake.company,
    'job_title': _fake.job,
}


def mask_value(provider: str, max_length: int | None = None) -> str:
    generator = PROVIDERS.get(provider)
    if generator is None:
        raise ValueError(f'Unknown masking provider: {provider!r}')
    value = str(generator())
    if max_length is not None and len(value) > max_length:
        value = value[:max_length]
    return value
