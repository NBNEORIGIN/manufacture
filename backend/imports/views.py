from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import ImportLog
from .parsers import PARSERS, detect_report_type
from .services import APPLIERS


class UploadReportView(APIView):
    def post(self, request):
        file = request.FILES.get('file')
        report_type = request.data.get('report_type', '')
        confirm = request.data.get('confirm', '').lower() == 'true'

        if not file:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            content = file.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            try:
                file.seek(0)
                content = file.read().decode('latin-1')
            except Exception:
                return Response({'error': 'Cannot decode file'}, status=status.HTTP_400_BAD_REQUEST)

        if not report_type:
            report_type = detect_report_type(content)
            if not report_type:
                return Response({
                    'error': 'Cannot detect report type. Please specify report_type.',
                    'options': list(PARSERS.keys()),
                }, status=status.HTTP_400_BAD_REQUEST)

        if report_type not in PARSERS:
            return Response({
                'error': f'Unknown report type: {report_type}',
                'options': list(PARSERS.keys()),
            }, status=status.HTTP_400_BAD_REQUEST)

        parsed = PARSERS[report_type](content)

        if not parsed['items']:
            return Response({
                'error': 'No items found in file',
                'report_type': report_type,
            }, status=status.HTTP_400_BAD_REQUEST)

        applier = APPLIERS.get(report_type)
        if not applier:
            return Response({'error': f'No applier for {report_type}'}, status=status.HTTP_400_BAD_REQUEST)

        result = applier(parsed, preview_only=not confirm)

        if confirm:
            user = request.user if request.user.is_authenticated else None
            ImportLog.objects.create(
                import_type=report_type,
                filename=file.name,
                rows_processed=result['total_items'],
                rows_created=0,
                rows_updated=len(result['changes']),
                rows_skipped=len(result['skipped']),
                errors=[s for s in result['skipped'][:50]],
                imported_by=user,
            )

        return Response(result)


class ImportHistoryView(APIView):
    def get(self, request):
        logs = ImportLog.objects.all()[:50]
        data = [
            {
                'id': log.id,
                'import_type': log.get_import_type_display(),
                'filename': log.filename,
                'rows_processed': log.rows_processed,
                'rows_created': log.rows_created,
                'rows_updated': log.rows_updated,
                'rows_skipped': log.rows_skipped,
                'error_count': len(log.errors) if log.errors else 0,
                'created_at': log.created_at,
            }
            for log in logs
        ]
        return Response(data)
