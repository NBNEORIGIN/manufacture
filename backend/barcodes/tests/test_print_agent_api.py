import pytest
import threading
from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APIClient
from barcodes.models import ProductBarcode, PrintJob
from products.models import Product


AGENT_TOKEN = 'test-agent-token-abc123'


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


@override_settings(
    LABEL_COMMAND_LANGUAGE='zpl',
    LABEL_WIDTH_MM=50.0,
    LABEL_HEIGHT_MM=25.0,
    LABEL_DPI=203,
    LABEL_WIDTH_DOTS=399,
    LABEL_HEIGHT_DOTS=199,
    PRINT_AGENT_TOKEN=AGENT_TOKEN,
)
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
