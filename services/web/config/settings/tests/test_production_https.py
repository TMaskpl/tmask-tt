import importlib


def test_production_settings_have_secure_proxy_ssl_header():
    production = importlib.import_module('config.settings.production')
    assert production.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https')


def test_production_settings_have_secure_cookies():
    production = importlib.import_module('config.settings.production')
    assert production.SESSION_COOKIE_SECURE is True
    assert production.CSRF_COOKIE_SECURE is True
