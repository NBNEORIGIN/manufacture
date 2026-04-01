from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import ImportLog


class UploadReportView(APIView):
    def post(self, request):
        return Response(
            {'message': 'CSV upload endpoint — Phase 3 implementation'},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


class ImportHistoryView(APIView):
    def get(self, request):
        logs = ImportLog.objects.all()[:50]
        data = [
            {
                'id': log.id,
                'import_type': log.import_type,
                'filename': log.filename,
                'rows_processed': log.rows_processed,
                'rows_created': log.rows_created,
                'rows_updated': log.rows_updated,
                'rows_skipped': log.rows_skipped,
                'errors': log.errors,
                'created_at': log.created_at,
            }
            for log in logs
        ]
        return Response(data)
