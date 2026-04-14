"""
DRF views for the JobAssignment model (Ivan review #8 items 1+2, #10 items 1-4).

Endpoints:
- GET    /api/assignments/            — list all (filterable by ?assigned_to=me&status=pending)
- POST   /api/assignments/            — create (accepts m_number instead of product ID)
- GET    /api/assignments/{id}/       — detail
- DELETE /api/assignments/{id}/       — cancel / remove
- POST   /api/assignments/{id}/complete/ — mark as completed
- GET    /api/assignments/pending-count/ — badge count for inbox icon
- POST   /api/assignments/mark-seen/    — clear unseen flag when inbox opens
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.auth_views import _display_name
from production.models_assignment import JobAssignment


class JobAssignmentSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)
    assigned_to_username = serializers.SerializerMethodField()
    assigned_by_username = serializers.SerializerMethodField()
    # Accept m_number on create (write-only)
    m_number_input = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = JobAssignment
        fields = [
            'id', 'product', 'm_number', 'description',
            'assigned_to', 'assigned_to_username',
            'assigned_by', 'assigned_by_username',
            'quantity', 'notes', 'status', 'seen',
            'completed_at', 'created_at',
            'm_number_input',
        ]
        read_only_fields = ['assigned_by', 'status', 'completed_at', 'seen', 'created_at']
        extra_kwargs = {
            'product': {'required': False},
        }

    def get_assigned_to_username(self, obj) -> str:
        return _display_name(obj.assigned_to) if obj.assigned_to else ''

    def get_assigned_by_username(self, obj) -> str:
        return _display_name(obj.assigned_by) if obj.assigned_by else ''

    def validate(self, data):
        m_input = data.pop('m_number_input', None)
        if m_input:
            from products.models import Product
            try:
                m = m_input.strip().upper()
                if not m.startswith('M'):
                    m = 'M' + m
                product = Product.objects.get(m_number=m)
                data['product'] = product
            except Product.DoesNotExist:
                raise serializers.ValidationError(
                    {'m_number_input': f'No product found with M-number "{m_input}"'}
                )
        if 'product' not in data:
            raise serializers.ValidationError(
                {'product': 'Either product or m_number_input is required'}
            )
        return data


class JobAssignmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = JobAssignmentSerializer
    queryset = JobAssignment.objects.select_related(
        'product', 'assigned_to', 'assigned_by',
    )

    def get_queryset(self):
        qs = super().get_queryset()
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
        JobAssignment.objects.filter(
            assigned_to=request.user,
            status='pending',
            seen=False,
        ).update(seen=True)
        return Response({'ok': True})
