"""
Unit tests for fba_shipments.services.sp_api_client.

These tests never touch the network. The FBAInboundClient constructor accepts
a `_client=` kwarg for dependency injection; we pass a MagicMock that records
calls and returns canned payloads.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from fba_shipments.models import FBAAPICall, FBAShipmentPlan
from fba_shipments.services import sp_api_client as sp_mod
from fba_shipments.services.sp_api_client import (
    FBAInboundClient,
    _extract_operation_id,
    _extract_payload,
    _safe_json,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def plan(db):
    return FBAShipmentPlan.objects.create(
        name='Test UK 2026-04-10',
        marketplace='UK',
        ship_from_address={
            'name': 'NBNE',
            'addressLine1': '1 Test Street',
            'city': 'Alnwick',
            'countryCode': 'GB',
            'postalCode': 'NE66 1AA',
        },
        status='items_added',
    )


@pytest.fixture
def mock_inner_client():
    """MagicMock standing in for a saleweaver FulfillmentInboundV20240320 instance."""
    return MagicMock(name='mock_saleweaver_client')


@pytest.fixture
def client(plan, mock_inner_client):
    return FBAInboundClient(marketplace_code='UK', plan=plan, _client=mock_inner_client)


class _FakeApiResponse:
    """Mimics saleweaver's ApiResponse shape: exposes .payload."""
    def __init__(self, payload):
        self.payload = payload


# --------------------------------------------------------------------------- #
# _safe_json                                                                  #
# --------------------------------------------------------------------------- #


class TestSafeJson:
    def test_none_passthrough(self):
        assert _safe_json(None) is None

    def test_plain_dict_passthrough(self):
        src = {'a': 1, 'b': 'two', 'c': [1, 2, 3]}
        assert _safe_json(src) == src

    def test_decimal_is_stringified(self):
        # Decimals are not natively JSON serialisable — json dumps with
        # default=str stringifies them. The important thing is "does not raise".
        result = _safe_json({'weight': Decimal('2.5')})
        assert result == {'weight': '2.5'}

    def test_nested_decimal(self):
        result = _safe_json({'box': {'weight': Decimal('1.25'), 'qty': 3}})
        assert result == {'box': {'weight': '1.25', 'qty': 3}}

    def test_unserialisable_object_does_not_crash(self):
        class Weird:
            def __repr__(self):
                return 'WeirdObj'
        result = _safe_json({'obj': Weird()})
        # Either the str() fallback kicks in (dict returned) or the last-ditch
        # branch fires. Both are acceptable; the point is no exception.
        assert isinstance(result, dict)


# --------------------------------------------------------------------------- #
# _extract_payload / _extract_operation_id                                    #
# --------------------------------------------------------------------------- #


class TestExtractHelpers:
    def test_extract_payload_from_api_response(self):
        resp = _FakeApiResponse({'key': 'value'})
        assert _extract_payload(resp) == {'key': 'value'}

    def test_extract_payload_from_raw_dict(self):
        assert _extract_payload({'key': 'value'}) == {'key': 'value'}

    def test_extract_operation_id_present(self):
        assert _extract_operation_id({'operationId': 'abc123'}) == 'abc123'

    def test_extract_operation_id_missing(self):
        assert _extract_operation_id({'other': 'thing'}) == ''

    def test_extract_operation_id_non_dict(self):
        assert _extract_operation_id(None) == ''
        assert _extract_operation_id('string') == ''


# --------------------------------------------------------------------------- #
# _call machinery: success, error, retry                                      #
# --------------------------------------------------------------------------- #


class TestCallSuccess:
    def test_successful_call_logs_api_call_row(self, client, mock_inner_client, plan):
        mock_inner_client.create_inbound_plan.return_value = _FakeApiResponse(
            {'inboundPlanId': 'wf-123', 'operationId': 'op-abc'}
        )

        payload = client.create_inbound_plan(
            {'destinationMarketplaces': ['A1F83G8C2ARO7P'], 'items': []}
        )

        assert payload == {'inboundPlanId': 'wf-123', 'operationId': 'op-abc'}
        mock_inner_client.create_inbound_plan.assert_called_once()

        # Exactly one FBAAPICall logged, linked to the plan, success status
        calls = FBAAPICall.objects.filter(plan=plan)
        assert calls.count() == 1
        call = calls.first()
        assert call.operation_name == 'createInboundPlan'
        assert call.response_status == 200
        assert call.operation_id == 'op-abc'
        assert call.error_message == ''
        assert call.duration_ms is not None
        assert call.request_body is not None
        assert 'destinationMarketplaces' in call.request_body

    def test_successful_call_without_plan_still_logs(self, db, mock_inner_client):
        mock_inner_client.list_inbound_plans.return_value = _FakeApiResponse(
            {'inboundPlans': []}
        )
        c = FBAInboundClient(marketplace_code='UK', plan=None, _client=mock_inner_client)
        c.list_inbound_plans()
        calls = FBAAPICall.objects.filter(operation_name='listInboundPlans')
        assert calls.count() == 1
        assert calls.first().plan is None

    def test_decimal_in_kwargs_is_coerced(self, client, mock_inner_client):
        """Regression: a Decimal in the request body must not crash the logger."""
        mock_inner_client.set_packing_information.return_value = _FakeApiResponse(
            {'operationId': 'op-xyz'}
        )
        body = {
            'packageGroupings': [
                {'boxes': [{'weight': {'value': Decimal('2.5'), 'unit': 'KG'}}]}
            ],
        }
        client.set_packing_information('wf-123', body)
        # Request body was persisted despite the Decimal
        row = FBAAPICall.objects.get(operation_name='setPackingInformation')
        assert row.request_body is not None


class TestCallErrors:
    def test_selling_api_exception_logs_and_reraises(self, client, mock_inner_client, plan):
        # saleweaver 2.1.8: SellingApiException(error, headers); exposes
        # .code (HTTP), .error (list), .amzn_code, .headers, .message.
        err = sp_mod.SellingApiException(
            error=[{'code': 'InvalidInput', 'message': 'nope'}],
            headers={},
        )
        err.code = 400  # type: ignore[attr-defined]
        mock_inner_client.create_inbound_plan.side_effect = err

        with pytest.raises(sp_mod.SellingApiException):
            client.create_inbound_plan({'items': []})

        call = FBAAPICall.objects.get(plan=plan, operation_name='createInboundPlan')
        assert call.response_status == 400
        assert call.error_message  # non-empty
        # Wrapper stored the error list under response_body.errors
        assert call.response_body is not None
        assert call.response_body.get('errors') == [
            {'code': 'InvalidInput', 'message': 'nope'}
        ]

    def test_throttle_retries_then_succeeds(self, client, mock_inner_client, plan):
        throttle = sp_mod.SellingApiRequestThrottledException(
            error=[{'code': 'QuotaExceeded'}]
        )
        mock_inner_client.generate_packing_options.side_effect = [
            throttle,
            throttle,
            _FakeApiResponse({'operationId': 'op-ok'}),
        ]
        with patch('fba_shipments.services.sp_api_client.time.sleep') as slp:
            payload = client.generate_packing_options('wf-123')
        assert payload == {'operationId': 'op-ok'}
        assert mock_inner_client.generate_packing_options.call_count == 3
        # Exponential backoff — slept twice (after the two throttles)
        assert slp.call_count == 2

        # Only one successful API call row (throttles don't log until exhaustion)
        rows = FBAAPICall.objects.filter(plan=plan, operation_name='generatePackingOptions')
        assert rows.count() == 1
        assert rows.first().response_status == 200

    def test_throttle_exhausts_retries_and_logs_429(self, client, mock_inner_client, plan):
        throttle = sp_mod.SellingApiRequestThrottledException(
            error=[{'code': 'QuotaExceeded'}]
        )
        mock_inner_client.generate_placement_options.side_effect = throttle
        with patch('fba_shipments.services.sp_api_client.time.sleep'):
            with pytest.raises(sp_mod.SellingApiRequestThrottledException):
                client.generate_placement_options('wf-123')

        # All MAX_RETRIES attempts were made
        assert mock_inner_client.generate_placement_options.call_count == sp_mod.MAX_RETRIES

        # Exactly one FBAAPICall row with status 429 logged after exhaustion
        rows = FBAAPICall.objects.filter(
            plan=plan, operation_name='generatePlacementOptions'
        )
        assert rows.count() == 1
        assert rows.first().response_status == 429


# --------------------------------------------------------------------------- #
# Method wrappers — spot checks that args are forwarded correctly            #
# --------------------------------------------------------------------------- #


class TestMethodWrappers:
    def test_create_inbound_plan_splats_body(self, client, mock_inner_client):
        mock_inner_client.create_inbound_plan.return_value = _FakeApiResponse({})
        client.create_inbound_plan({'destinationMarketplaces': ['X'], 'items': []})
        _, kwargs = mock_inner_client.create_inbound_plan.call_args
        # Body was splatted into kwargs, not wrapped in body=
        assert kwargs == {'destinationMarketplaces': ['X'], 'items': []}

    def test_set_packing_information_positional_plan_id(self, client, mock_inner_client):
        mock_inner_client.set_packing_information.return_value = _FakeApiResponse({})
        client.set_packing_information('wf-999', {'packageGroupings': []})
        args, kwargs = mock_inner_client.set_packing_information.call_args
        assert args == ('wf-999',)
        assert kwargs == {'packageGroupings': []}

    def test_confirm_packing_option_positionals(self, client, mock_inner_client):
        mock_inner_client.confirm_packing_option.return_value = _FakeApiResponse({})
        client.confirm_packing_option('wf-1', 'po-1')
        args, _ = mock_inner_client.confirm_packing_option.call_args
        assert args == ('wf-1', 'po-1')

    def test_get_operation_status_uses_positional(self, client, mock_inner_client):
        mock_inner_client.get_inbound_operation_status.return_value = _FakeApiResponse(
            {'operationStatus': 'SUCCESS'}
        )
        client.get_operation_status('op-1')
        args, _ = mock_inner_client.get_inbound_operation_status.call_args
        assert args == ('op-1',)

    def test_get_labels_passes_query_params(self, client, mock_inner_client):
        mock_inner_client.get_labels.return_value = _FakeApiResponse({'url': 'http://x'})
        client.get_labels('FBA15ABCDEFG')
        args, kwargs = mock_inner_client.get_labels.call_args
        assert args == ('FBA15ABCDEFG',)
        assert kwargs['PageType'] == 'PackageLabel_Plain_Paper'
        assert kwargs['LabelType'] == 'UNIQUE'


class TestGetLabelsV0Fallback:
    def test_get_labels_v0_swaps_client_for_one_call(self, client, mock_inner_client):
        """The v0 fallback should log as 'getLabels (v0)' and not leak into later calls."""
        original_client_id = id(client._client)

        # Patch the FulfillmentInboundV0 constructor to return a mock
        fake_v0 = MagicMock(name='fake_v0')
        fake_v0.get_labels.return_value = _FakeApiResponse({'url': 'http://v0'})
        with patch.object(sp_mod, 'FulfillmentInboundV0', return_value=fake_v0):
            result = client.get_labels_v0('FBA15ABCDEFG')

        assert result == {'url': 'http://v0'}
        fake_v0.get_labels.assert_called_once()
        # After the call, client._client must be restored to the original
        assert id(client._client) == original_client_id

        row = FBAAPICall.objects.get(operation_name='getLabels (v0)')
        assert row.response_status == 200


# --------------------------------------------------------------------------- #
# poll_operation                                                              #
# --------------------------------------------------------------------------- #


class TestPollOperation:
    def test_returns_on_success(self, client, mock_inner_client):
        mock_inner_client.get_inbound_operation_status.return_value = _FakeApiResponse(
            {'operationStatus': 'SUCCESS', 'operationId': 'op-1'}
        )
        with patch('fba_shipments.services.sp_api_client.time.sleep'):
            payload = client.poll_operation('op-1', timeout=10, interval=1)
        assert payload['operationStatus'] == 'SUCCESS'

    def test_raises_on_failed(self, client, mock_inner_client):
        mock_inner_client.get_inbound_operation_status.return_value = _FakeApiResponse(
            {
                'operationStatus': 'FAILED',
                'operationProblems': [{'code': 'FBA_INB_0182', 'message': 'prep missing'}],
            }
        )
        with patch('fba_shipments.services.sp_api_client.time.sleep'):
            with pytest.raises(RuntimeError, match='failed'):
                client.poll_operation('op-1', timeout=10, interval=1)

    def test_times_out_when_still_in_progress(self, client, mock_inner_client):
        mock_inner_client.get_inbound_operation_status.return_value = _FakeApiResponse(
            {'operationStatus': 'IN_PROGRESS'}
        )
        # Simulate time advancing past the deadline after a single poll
        # by patching time.monotonic to return increasing values.
        monotonic_values = iter([0.0, 0.0, 100.0, 100.0])
        with patch(
            'fba_shipments.services.sp_api_client.time.monotonic',
            side_effect=lambda: next(monotonic_values),
        ):
            with patch('fba_shipments.services.sp_api_client.time.sleep'):
                with pytest.raises(TimeoutError):
                    client.poll_operation('op-1', timeout=5, interval=1)

    def test_rejects_zero_timeout(self, client):
        with pytest.raises(ValueError):
            client.poll_operation('op-1', timeout=0)
