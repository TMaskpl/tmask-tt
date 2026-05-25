from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.users_list, name='users'),
    path('profile/', views.profile_view, name='profile'),
    path('test-webhook/', views.test_webhook, name='test_webhook'),
]
