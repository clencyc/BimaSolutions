"""
URL configuration for backendapi project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from . import model_api, interpretation_api, upload_api

urlpatterns = [
    path('admin/', admin.site.urls),
    path('auth/', include('users.urls')),
    path('api/upload/', upload_api.upload_and_extract, name='api-upload'),
    path('api/interpretation/health/', interpretation_api.interpretation_health, name='interpretation-health'),
    path('api/interpretation/summary/', interpretation_api.interpretation_summary, name='interpretation-summary'),
    path('api/interpretation/question/', interpretation_api.interpretation_question, name='interpretation-question'),
    path('api/model/health/', model_api.model_health, name='model-health'),
    path('api/model/buildings/', model_api.model_buildings, name='model-buildings'),
    path(
        'api/model/portfolio-summary/',
        model_api.model_portfolio_summary,
        name='model-portfolio-summary',
    ),
    path('api/model/metrics/', model_api.model_metrics, name='model-metrics'),
    path('api/model/formula/', model_api.model_formula, name='model-formula'),
    path('api/model/extract/', model_api.model_extract_data, name='model-extract'),
    path(
        'api/model/quote/<str:building_id>/',
        model_api.model_building_quote,
        name='model-building-quote',
    ),
    path('api/model/quote/', model_api.model_custom_quote, name='model-custom-quote'),
]
