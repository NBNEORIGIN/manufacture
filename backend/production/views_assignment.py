"""
DRF views for the JobAssignment model (Ivan review #8 items 1+2, #10 items 1-4, #11 items 1-3).

Endpoints:
- GET    /api/assignments/            — list all (filterable by ?assigned_to=me&status=pending)
- POST   /api/assignments/            — create (accepts m_number, assigned_user_ids list)
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
from production.models_assignment import JobAssignment, JobAssignmentUser


class JobAssignmentSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)
    assigned_by_username = serializers.SerializerMethodField()
    assigned_usernames = serializers.SerializerMethodField()
    assigned_user_ids = serializers.SerializerMethodField()

    # Write-only
    m_number_input = serializers.CharField(write_only=True, required=False)
    assigned_users_input = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=True,
        min_length=1, max_length=4,
    )

    class Meta:
        model = JobAssignment
        fields = [
            'id', 'product', 'm_number', 'description',
            'assigned_usernames', 'assigned_user_ids',
            'assigned_by', 'assigned_by_username',
            'quantity', 'notes', 'status',
            'completed_at', 'created_at',
            'm_number_input', 'assigned_users_input',
        ]
        read_only_fields = ['assigned_by', 'status', 'completed_at', 'created_at']
        extra_kwargs = {
            'product': {'required': False},
        }

    def get_assigned_by_username(self, obj) -> str:
        return _display_name(obj.assigned_by) if obj.assigned_by else ''

    def get_assigned_usernames(self, obj) -> list[str]:
        return [
            _display_name(au.user)
            for au in obj.assignment_users.select_related('user').all()
        ]

    def get_assigned_user_ids(self, obj) -> list[int]:
        return list(obj.assignment_users.values_list('user_id', flat=True))

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

    def create(self, validated_data):
        user_ids = validated_data.pop('assigned_users_input', [])
        assignment = JobAssignment.objects.create(**validated_data)
        for uid in user_ids:
            JobAssignmentUser.objects.create(
                assignment=assignment, user_id=uid, seen=False,
            )
        return assignment


class JobAssignmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = JobAssignmentSerializer
    queryset = JobAssignment.objects.select_related(
        'product', 'assigned_by',
    ).prefetch_related('assignment_users', 'assignment_users__user')

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('assigned_to') == 'me':
            qs = qs.filter(assignment_users__user=self.request.user)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.distinct()

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
        user_links = JobAssignmentUser.objects.filter(
            user=request.user,
            assignment__status='pending',
        )
        count = user_links.count()
        unseen = user_links.filter(seen=False).count()
        return Response({'count': count, 'unseen': unseen})

    @action(detail=False, methods=['post'], url_path='mark-seen')
    def mark_seen(self, request):
        JobAssignmentUser.objects.filter(
            user=request.user,
            assignment__status='pending',
            seen=False,
        ).update(seen=True)
        return Response({'ok': True})
