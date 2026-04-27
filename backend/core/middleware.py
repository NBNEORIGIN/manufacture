"""
NoCacheApiMiddleware — adds Cache-Control: no-store to every /api/ response.

Two browsers logged in as different users were seeing different data on the
D2C page. The DRF queryset is identical for everyone (no per-user filtering),
so the only thing that could differ is a stale cached response sitting in a
proxy / CDN / browser. This middleware closes that door at the application
layer — the API never returns a cacheable response, full stop.
"""
from typing import Callable

from django.http import HttpRequest, HttpResponse


class NoCacheApiMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.path.startswith('/api/'):
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        return response
