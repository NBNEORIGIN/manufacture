from django.urls import path
from . import views

urlpatterns = [
    path('marketplaces/', views.marketplaces_view, name='restock-marketplaces'),
    path('history/', views.history_view, name='restock-history'),
    path('approve/', views.approve_view, name='restock-approve'),
    path('create-production/', views.create_production_view, name='restock-create-production'),
    path('upload/', views.upload_view, name='restock-upload'),
    path('exclusions/', views.exclusions_view, name='restock-exclusions'),
    path('<str:marketplace>/sync/', views.sync_view, name='restock-sync'),
    path('<str:marketplace>/status/', views.status_view, name='restock-status'),
    path('<str:marketplace>/', views.plan_view, name='restock-plan'),
]
