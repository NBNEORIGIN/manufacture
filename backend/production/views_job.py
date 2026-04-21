"""
DRF views for multi-step threaded jobs (Ivan review #10 item 5, #11 items 3-7).

Endpoints:
- GET    /api/jobs/                         — list all jobs
- POST   /api/jobs/                         — create a job with steps
- GET    /api/jobs/{id}/                    — detail with all steps
- DELETE /api/jobs/{id}/                    — remove
- POST   /api/jobs/{id}/steps/{step_number}/complete/  — complete a step
- GET    /api/jobs/my-active-steps/         — current user's active steps (for inbox)
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.auth_views import _display_name
from production.models_job import Job, JobStep, JobStepUser


class JobStepSerializer(serializers.ModelSerializer):
    assigned_to_names = serializers.SerializerMethodField()
    assigned_to_ids = serializers.SerializerMethodField()
    completed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = JobStep
        fields = [
            'id', 'step_number', 'assigned_to_ids', 'assigned_to_names',
            'description', 'status',
            'completed_at', 'completed_by', 'completed_by_name',
        ]
        read_only_fields = [
            'status', 'completed_at', 'completed_by',
        ]

    def get_assigned_to_names(self, obj) -> list[str]:
        return [
            _display_name(su.user)
            for su in obj.step_users.select_related('user').all()
        ]

    def get_assigned_to_ids(self, obj) -> list[int]:
        return list(obj.step_users.values_list('user_id', flat=True))

    def get_completed_by_name(self, obj) -> str:
        return _display_name(obj.completed_by) if obj.completed_by else ''


class JobSerializer(serializers.ModelSerializer):
    m_number = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    steps = JobStepSerializer(many=True, read_only=True)
    step_chain = serializers.CharField(source='step_chain_display', read_only=True)

    # Write-only fields for creation
    m_number_input = serializers.CharField(write_only=True, required=False)
    steps_input = serializers.ListField(
        child=serializers.DictField(), write_only=True, required=False,
    )

    class Meta:
        model = Job
        fields = [
            'id', 'product', 'm_number', 'description',
            'created_by', 'created_by_name',
            'title', 'notes', 'status', 'completed_at',
            'customer', 'deadline', 'asap',
            'steps', 'step_chain',
            'm_number_input', 'steps_input',
            'created_at',
        ]
        read_only_fields = ['created_by', 'status', 'completed_at', 'created_at']
        extra_kwargs = {'product': {'required': False}}

    def get_m_number(self, obj) -> str:
        return obj.product.m_number if obj.product else ''

    def get_description(self, obj) -> str:
        return obj.product.description if obj.product else ''

    def get_created_by_name(self, obj) -> str:
        return _display_name(obj.created_by) if obj.created_by else ''

    def validate(self, data):
        m_input = data.pop('m_number_input', None)
        if m_input:
            from products.models import Product
            m = m_input.strip().upper()
            if not m.startswith('M'):
                m = 'M' + m
            try:
                data['product'] = Product.objects.get(m_number=m)
            except Product.DoesNotExist:
                raise serializers.ValidationError(
                    {'m_number_input': f'No product "{m_input}"'}
                )
        # product is now optional (threaded jobs may have title only)
        steps = data.pop('steps_input', None)
        if steps:
            if len(steps) < 1:
                raise serializers.ValidationError(
                    {'steps_input': 'At least one step required'}
                )
            data['_steps'] = steps
        else:
            data['_steps'] = []
        return data

    def create(self, validated_data):
        steps_data = validated_data.pop('_steps', [])
        job = Job.objects.create(**validated_data)

        for i, step in enumerate(steps_data, start=1):
            js = JobStep.objects.create(
                job=job,
                step_number=i,
                description=step.get('description', ''),
                status='active' if i == 1 else 'waiting',
            )
            # assigned_to can be a single int or a list of ints
            user_ids = step.get('assigned_to_ids', [])
            if not user_ids:
                # backwards compat: single assigned_to field
                single = step.get('assigned_to')
                if single:
                    user_ids = [single]
            for uid in user_ids[:4]:  # cap at 4
                JobStepUser.objects.create(
                    step=js, user_id=uid, seen=False,
                )

        if steps_data:
            job.status = 'in_progress'
            job.save(update_fields=['status'])

        return job


class JobViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = JobSerializer
    queryset = Job.objects.select_related('product', 'created_by').prefetch_related(
        'steps', 'steps__step_users', 'steps__step_users__user', 'steps__completed_by',
    )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(
        detail=True,
        methods=['post'],
        url_path=r'steps/(?P<step_number>\d+)/complete',
    )
    def complete_step(self, request, pk=None, step_number=None):
        """
        Mark a step as completed. Rules:
        - Only the job creator or one of the step's assigned users can complete it.
        - When step N completes, step N+1 becomes active.
        - When the last step completes, the Job status becomes 'completed'.
        """
        job = self.get_object()
        try:
            step = job.steps.get(step_number=int(step_number))
        except JobStep.DoesNotExist:
            return Response(
                {'error': f'Step {step_number} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if step.status != 'active':
            return Response(
                {'error': f'Step {step_number} is {step.status}, not active'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Permission: creator or one of the assigned users
        step_user_ids = set(step.step_users.values_list('user_id', flat=True))
        if request.user != job.created_by and request.user.id not in step_user_ids:
            return Response(
                {'error': 'Only the job creator or an assigned user can complete this step'},
                status=status.HTTP_403_FORBIDDEN,
            )

        step.status = 'completed'
        step.completed_at = timezone.now()
        step.completed_by = request.user
        step.save(update_fields=['status', 'completed_at', 'completed_by'])

        # Activate next step if one exists
        next_step = job.steps.filter(
            step_number=int(step_number) + 1,
        ).first()
        if next_step:
            next_step.status = 'active'
            next_step.save(update_fields=['status'])
            # Reset seen flags on all users of next step so they get notified
            next_step.step_users.update(seen=False)
        else:
            # Last step — mark job as completed
            job.status = 'completed'
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'completed_at'])

        return Response({
            'ok': True,
            'step_completed': int(step_number),
            'next_step_activated': next_step.step_number if next_step else None,
            'job_completed': job.status == 'completed',
        })

    @action(detail=False, methods=['get'], url_path='my-active-steps')
    def my_active_steps(self, request):
        """
        Returns the current user's active (and unseen) job steps.
        Used by InboxButton alongside the existing pending-count.
        """
        step_user_links = (
            JobStepUser.objects
            .filter(user=request.user, step__status='active')
            .select_related('step', 'step__job', 'step__job__product', 'step__job__created_by')
            .order_by('-step__job__created_at')
        )
        return Response({
            'steps': [
                {
                    'job_id': su.step.job_id,
                    'm_number': su.step.job.product.m_number if su.step.job.product else '',
                    'description': su.step.job.product.description if su.step.job.product else '',
                    'step_number': su.step.step_number,
                    'step_description': su.step.description,
                    'created_by': _display_name(su.step.job.created_by),
                    'seen': su.seen,
                    'job_title': su.step.job.title,
                }
                for su in step_user_links
            ],
            'count': step_user_links.count(),
            'unseen': step_user_links.filter(seen=False).count(),
        })

    @action(detail=False, methods=['post'], url_path='mark-steps-seen')
    def mark_steps_seen(self, request):
        """Mark all active step notifications as seen for the current user."""
        JobStepUser.objects.filter(
            user=request.user,
            step__status='active',
            seen=False,
        ).update(seen=True)
        return Response({'ok': True})
