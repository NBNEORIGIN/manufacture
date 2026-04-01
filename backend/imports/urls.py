from django.urls import path
from .views import UploadReportView, ImportHistoryView

urlpatterns = [
    path('upload/', UploadReportView.as_view(), name='import-upload'),
    path('history/', ImportHistoryView.as_view(), name='import-history'),
]
