from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings


class PrintAgentAuthentication(BaseAuthentication):
    """
    Simple shared-secret auth for the print agent.

    Not tied to a User — the agent is infrastructure, not a person.
    Returns (None, None) on success, which is DRF's convention for
    "authenticated but no user attached".
    """

    def authenticate(self, request):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Token '):
            return None  # defer to other auth classes

        provided_token = header[len('Token '):].strip()
        expected_token = getattr(settings, 'PRINT_AGENT_TOKEN', '')

        if not expected_token:
            raise AuthenticationFailed('PRINT_AGENT_TOKEN not configured on server')
        if provided_token != expected_token:
            raise AuthenticationFailed('Invalid agent token')

        return (None, None)

    def authenticate_header(self, request):
        return 'Token'
