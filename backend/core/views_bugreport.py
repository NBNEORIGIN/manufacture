import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status


@api_view(['POST'])
@permission_classes([AllowAny])
def bugreport_view(request):
    subject = request.data.get('subject', 'Bug Report')
    description = request.data.get('description', '')
    steps = request.data.get('steps_to_reproduce', '')
    reporter = request.data.get('reporter', 'Anonymous')
    page = request.data.get('page', '')

    if not description:
        return Response({'error': 'Description is required'}, status=status.HTTP_400_BAD_REQUEST)

    html = f"""
    <html><body>
    <h2 style="color:#dc2626;">[Manufacture] Bug Report</h2>
    <table style="border-collapse:collapse;width:100%;max-width:600px;">
        <tr style="border-bottom:1px solid #ddd;">
            <td style="padding:8px;font-weight:bold;width:120px;">Reporter</td>
            <td style="padding:8px;">{reporter}</td>
        </tr>
        <tr style="border-bottom:1px solid #ddd;">
            <td style="padding:8px;font-weight:bold;">Page</td>
            <td style="padding:8px;">{page}</td>
        </tr>
        <tr style="border-bottom:1px solid #ddd;">
            <td style="padding:8px;font-weight:bold;">Time</td>
            <td style="padding:8px;">{datetime.now().strftime('%Y-%m-%d %H:%M')}</td>
        </tr>
        <tr style="border-bottom:1px solid #ddd;">
            <td style="padding:8px;font-weight:bold;">Description</td>
            <td style="padding:8px;">{description}</td>
        </tr>
        <tr>
            <td style="padding:8px;font-weight:bold;">Steps</td>
            <td style="padding:8px;">{steps or 'Not provided'}</td>
        </tr>
    </table>
    </body></html>
    """

    smtp_host = settings.SMTP_HOST
    smtp_port = settings.SMTP_PORT
    smtp_user = settings.SMTP_USER
    smtp_pass = settings.SMTP_PASSWORD

    if not smtp_user or not smtp_pass:
        return Response({'error': 'SMTP not configured'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    recipients = ['toby@nbnesigns.com', 'gabby@nbnesigns.com']

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'[Manufacture] {subject}'
    msg['From'] = smtp_user
    msg['To'] = ', '.join(recipients)
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipients, msg.as_string())
        return Response({'message': 'Bug report sent'})
    except Exception as e:
        return Response({'error': f'Failed to send: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
