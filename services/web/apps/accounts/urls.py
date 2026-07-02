from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.users_list, name='users'),
    path('users/new/', views.user_create, name='user_create'),
    path('users/<int:pk>/role/', views.change_user_role, name='change_user_role'),
    path('profile/', views.profile_view, name='profile'),
    path('2fa/setup/', views.totp_setup, name='2fa_setup'),
    path('2fa/recovery-codes/', views.totp_recovery_codes, name='2fa_recovery_codes'),
    path('2fa/verify/', views.totp_verify, name='2fa_verify'),
    path('2fa/disable/', views.totp_disable, name='2fa_disable'),
    path('test-webhook/', views.test_webhook, name='test_webhook'),
    path('api-tokens/generate/', views.generate_api_token, name='generate_api_token'),
    path('api-tokens/<int:token_id>/revoke/', views.revoke_api_token, name='revoke_api_token'),
]
