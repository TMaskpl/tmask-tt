from django.http import HttpResponse
from django.test import RequestFactory


def test_missing_header_returns_401(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = 'correct-token'

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/')
    response = dummy_view(request)
    assert response.status_code == 401
    assert response['WWW-Authenticate'] == 'Bearer'


def test_wrong_prefix_returns_401(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = 'correct-token'

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/', HTTP_AUTHORIZATION='Token correct-token')
    response = dummy_view(request)
    assert response.status_code == 401


def test_wrong_token_returns_401(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = 'correct-token'

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/', HTTP_AUTHORIZATION='Bearer wrong-token')
    response = dummy_view(request)
    assert response.status_code == 401


def test_correct_token_calls_view(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = 'correct-token'

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/', HTTP_AUTHORIZATION='Bearer correct-token')
    response = dummy_view(request)
    assert response.status_code == 200
    assert response.content == b'ok'


def test_empty_metrics_token_never_matches(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = ''

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/', HTTP_AUTHORIZATION='Bearer ')
    response = dummy_view(request)
    assert response.status_code == 401
