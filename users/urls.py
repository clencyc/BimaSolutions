from django.contrib import admin
from django.urls import path
from .views import login, logout, create_user

urlpatterns = [
    path('login/', login, name="login"),
    path('logout/', logout, name="logout"),
    path('create_user/', create_user, name="create_user")
]
