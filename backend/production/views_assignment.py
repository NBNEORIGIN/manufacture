"""
DRF views for the JobAssignment model (Ivan review #8, items 1+2).

Endpoints:
- GET    /api/assignments/            — list all (filterable by ?assigned_to=me&status=pending)
- POST   /api/assignments/            — create (assign product to user)
- GET    /api/assignments/{id}/       — detail
- DELETE /api/assignments/{id}/       — cancel
- POST   /api/assignments/{id}/complete/ — mark as completed
- GET    /api/assignments/pending-count/ — badge count for inbox icon
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from production.models_assignment import JobAssignment


class JobAssignmentSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)
    assigned_to_username = serializers.CharField(
        source='assigned_to.username', read_only=True,
    )
    assigned_by_username = serializers.CharField(
        source='assigned_by.username', read_only=True, default='',
    )

    class Meta:
        model = JobAssignment
        fields = [
            'id', 'product', 'm_number', 'description',
            'assigned_to', 'assigned_to_username',
            'assigned_by', 'assigned_by_username',
            'quantity', 'notes', 'status', 'seen',
            'completed_at', 'created_at',
        ]
        read_only_fields = ['assigned_by', 'status', 'completed_at', 'seen', 'created_at']


class JobAssignmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = JobAssignmentSerializer
    queryset = JobAssignment.objects.select_related(
        'product', 'assigned_to', 'assigned_by',
    )

    def get_queryset(self):
        qs = super().get_queryset()
        # Filter by assigned_to=me
        if self.request.query_params.get('assigned_to') == 'me':
            qs = qs.filter(assigned_to=self.request.user)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        obj = self.get_object()
        obj.status = 'completed'
        obj.completed_at = timezone.now()
        obj.save(update_fields=['status', 'completed_at'])
        return Response({'ok': True, 'status': 'completed'})

    @action(detail=False, methods=['get'], url_path='pending-count')
    def pending_count(self, request):
        count = JobAssignment.objects.filter(
            assigned_to=request.user,
            status='pending',
        ).count()
        unseen = JobAssignment.objects.filter(
            assigned_to=request.user,
            status='pending',
            seen=False,
        ).count()
        return Response({'count': count, 'unseen': unseen})

    @action(detail=False, methods=['post'], url_path='mark-seen')
    def mark_seen(self, request):
        """Mark all pending assignments for the current user as seen."""
        JobAssignment.objects.filter(
            assigned_to=request.user,
            status='pending',
            seen=False,
        ).update(seen=True)
        return Response({'ok': True})
