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
    report_type = request.data.get('report_type', 'bug')   # 'bug' or 'feature'
    subject = request.data.get('subject', '')
    description = request.data.get('description', '')
    steps = request.data.get('steps_to_reproduce', '')
    reporter = request.data.get('reporter', 'Anonymous')
    page = request.data.get('page', '')
    revision = request.data.get('revision', '')

    if not description:
        return Response({'error': 'Description is required'}, status=status.HTTP_400_BAD_REQUEST)

    is_feature = report_type == 'feature'
    colour = '#2563eb' if is_feature else '#dc2626'
    label = 'Feature Request' if is_feature else 'Bug Report'
    email_subject = f'[Manufacture] {label}: {subject}' if subject else f'[Manufacture] {label}'

    rows = [
        ('Reporter', reporter),
        ('Revision', revision or '—'),
        ('Page', page or '—'),
        ('Time', datetime.now().strftime('%Y-%m-%d %H:%M')),
        ('Description', description),
    ]
    if not is_feature and steps:
        rows.append(('Steps to reproduce', steps))

    row_html = ''.join(
        f'<tr style="border-bottom:1px solid #ddd;">'
        f'<td style="padding:8px;font-weight:bold;width:150px;">{k}</td>'
        f'<td style="padding:8px;">{v}</td>'
        f'</tr>'
        for k, v in rows
    )

    html = f"""
    <html><body>
    <h2 style="color:{colour};">[Manufacture] {label}</h2>
    <table style="border-collapse:collapse;width:100%;max-width:600px;">
        {row_html}
    </table>
    </body></html>
    """

    smtp_host = getattr(settings, 'SMTP_HOST', '')
    smtp_port = getattr(settings, 'SMTP_PORT', 587)
    smtp_user = getattr(settings, 'SMTP_USER', '')
    smtp_pass = getattr(settings, 'SMTP_PASSWORD', '')

    if not smtp_user or not smtp_pass:
        return Response({'error': 'SMTP not configured on server'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    recipients = ['toby@nbnesigns.com', 'gabby@nbnesigns.com']

    msg = MIMEMultipart('alternative')
    msg['Subject'] = email_subject
    msg['From'] = smtp_user
    msg['To'] = ', '.join(recipients)
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipients, msg.as_string())
        return Response({'message': f'{label} sent!'})
    except Exception as e:
        return Response(
            {'error': f'Failed to send: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
