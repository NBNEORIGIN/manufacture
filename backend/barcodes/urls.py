from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'barcodes', views.ProductBarcodeViewSet, basename='barcode')
router.register(r'print-jobs', views.PrintJobViewSet, basename='print-job')

urlpatterns = [
    path('', include(router.urls)),
    path('printers/', views.list_printers, name='printer-list'),
    path('print-agent/pending/', views.agent_pending, name='print-agent-pending'),
    path('print-agent/jobs/<int:job_id>/complete/', views.agent_complete, name='print-agent-complete'),
    path('print-agent/setup_printer.py', views.serve_setup_script, name='print-agent-setup-script'),
    path('print-agent/agent.py', views.serve_agent_script, name='print-agent-agent-script'),
]
