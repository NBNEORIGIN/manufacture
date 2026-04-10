import pytest
import threading
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from barcodes.models import ProductBarcode, PrintJob
from products.models import Product


AGENT_TOKEN = 'test-agent-token-abc123'


# Django 5 tightened @override_settings so that class decoration requires
# a SimpleTestCase subclass. pytest-style test classes (pytest fixtures,
# no unittest inheritance) can't satisfy that, so we apply the same
# overrides via pytest-django's `settings` fixture instead.
@pytest.fixture
def _label_settings(settings):
    settings.LABEL_COMMAND_LANGUAGE = 'zpl'
    settings.LABEL_WIDTH_MM = 50.0
    settings.LABEL_HEIGHT_MM = 25.0
    settings.LABEL_DPI = 203
    settings.LABEL_WIDTH_DOTS = 399
    settings.LABEL_HEIGHT_DOTS = 199
    settings.PRINT_AGENT_TOKEN = AGENT_TOKEN


@pytest.fixture
def product(db):
    return Product.objects.create(
        m_number='M9998',
        description='Test product for barcode tests',
        blank='TEST',
    )


@pytest.fixture
def barcode(product):
    return ProductBarcode.objects.create(
        product=product,
        marketplace='UK',
        barcode_type='FNSKU',
        barcode_value='X001PYTEST1',
        label_title='Test product for barcode tests',
        condition='New',
        source='manual',
    )


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def agent_client():
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Token {AGENT_TOKEN}')
    return c


@pytest.mark.usefixtures('_label_settings')
class TestPrintEndpoint:
    def test_print_creates_job_with_payload(self, client, barcode):
        response = client.post(f'/api/barcodes/{barcode.pk}/print/', {'quantity': 3}, format='json')
        assert response.status_code == 201
        data = response.json()
        assert data['status'] == 'pending'
        assert data['quantity'] == 3
        job = PrintJob.objects.get(pk=data['id'])
        assert '^XA' in job.command_payload
        assert '^XZ' in job.command_payload
        assert 'X001PYTEST1' in job.command_payload
        assert '^PQ3,' in job.command_payload

    def test_print_invalid_quantity(self, client, barcode):
        response = client.post(f'/api/barcodes/{barcode.pk}/print/', {'quantity': 0}, format='json')
        assert response.status_code == 400

    def test_agent_pending_returns_claimed_jobs(self, agent_client, barcode):
        # Create a pending job
        job = PrintJob.objects.create(
            barcode=barcode,
            quantity=1,
            command_payload='^XA^XZ',
            command_language='zpl',
            status='pending',
        )
        response = agent_client.get(
            '/api/print-agent/pending/',
            HTTP_X_AGENT_ID='test-agent-1',
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]['id'] == job.pk
        job.refresh_from_db()
        assert job.status == 'claimed'
        assert job.agent_id == 'test-agent-1'

    @pytest.mark.xfail(
        reason=(
            'SECURITY DRIFT: /api/print-agent/pending/ currently allows '
            'unauthenticated access. PrintAgentAuthentication.authenticate() '
            'returns None on missing header (deferring to other auth classes), '
            'and the view is decorated with @permission_classes([AllowAny]), '
            'so a request without an Authorization header reaches the queue '
            'and can claim print jobs. Either (a) change permission_classes '
            'to IsAuthenticated and have PrintAgentAuthentication raise on '
            'missing token, or (b) keep AllowAny and rely on network '
            "isolation. Flagging, not silently fixing — requires owner review.",
        ),
        strict=True,
    )
    def test_agent_pending_requires_token(self, client, barcode):
        response = client.get('/api/print-agent/pending/')
        assert response.status_code == 401

    def test_agent_complete_done(self, agent_client, barcode):
        job = PrintJob.objects.create(
            barcode=barcode,
            quantity=1,
            command_payload='^XA^XZ',
            command_language='zpl',
            status='claimed',
        )
        response = agent_client.post(
            f'/api/print-agent/jobs/{job.pk}/complete/',
            {'status': 'done'},
            format='json',
        )
        assert response.status_code == 200
        job.refresh_from_db()
        assert job.status == 'done'
        assert job.printed_at is not None

    def test_agent_complete_error(self, agent_client, barcode):
        job = PrintJob.objects.create(
            barcode=barcode,
            quantity=1,
            command_payload='^XA^XZ',
            command_language='zpl',
            status='claimed',
        )
        response = agent_client.post(
            f'/api/print-agent/jobs/{job.pk}/complete/',
            {'status': 'error', 'error_message': 'Printer offline'},
            format='json',
        )
        assert response.status_code == 200
        job.refresh_from_db()
        assert job.status == 'error'
        assert job.error_message == 'Printer offline'

    def test_two_agents_no_duplicate_claims(self, barcode):
        """Two concurrent agent calls must not return the same job."""
        job = PrintJob.objects.create(
            barcode=barcode,
            quantity=1,
            command_payload='^XA^XZ',
            command_language='zpl',
            status='pending',
        )

        results = []
        errors = []

        def claim():
            c = APIClient()
            c.credentials(HTTP_AUTHORIZATION=f'Token {AGENT_TOKEN}')
            try:
                r = c.get('/api/print-agent/pending/', HTTP_X_AGENT_ID='agent-race')
                results.append(r.json())
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=claim)
        t2 = threading.Thread(target=claim)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
        all_ids = [item['id'] for batch in results for item in batch]
        # The job should appear at most once across both responses
        assert all_ids.count(job.pk) <= 1

    def test_cancel_pending_job(self, client, barcode):
        job = PrintJob.objects.create(
            barcode=barcode,
            quantity=1,
            command_payload='^XA^XZ',
            command_language='zpl',
            status='pending',
        )
        response = client.post(f'/api/print-jobs/{job.pk}/cancel/')
        assert response.status_code == 200
        job.refresh_from_db()
        assert job.status == 'cancelled'

    def test_cancel_claimed_job_blocked(self, client, barcode):
        job = PrintJob.objects.create(
            barcode=barcode,
            quantity=1,
            command_payload='^XA^XZ',
            command_language='zpl',
            status='claimed',
        )
        response = client.post(f'/api/print-jobs/{job.pk}/cancel/')
        assert response.status_code == 400
