"""
Thin, logged, rate-limited wrapper around Amazon's SP-API Fulfillment Inbound
v2024-03-20 endpoints, plus the handful of helpers the FBA state machine needs.

Library inspection (python-amazon-sp-api v2.1.8, run during Phase 2.2):

    >>> import sp_api.api as a
    >>> [x for x in dir(a) if 'Inbound' in x]
    ['FbaInboundEligibility', 'FulfillmentInbound', 'FulfillmentInboundV0',
     'FulfillmentInboundV20240320', 'FulfillmentInboundVersion']

Key finding: `FulfillmentInboundV20240320` exposes EVERY method the 23-step
workflow needs — including `get_labels` (routed to `/fba/inbound/2024-03-20/
shipments/{}/labels`). The brief assumed we'd need a dedicated v0 client for
`get_labels`, but that is no longer true in saleweaver 2.x. We use a single
client for the entire module. `FulfillmentInboundV0` is kept importable as a
documented fallback in case Amazon's v2024 labels endpoint 404s for a given
shipment — but it is not wired in by default.

Sandbox caveat: saleweaver 2.x does NOT expose a clean sandbox toggle.
`Marketplaces.SANDBOX` does not exist and `Client.__init__` has no sandbox
kwarg. Hitting sandbox would require patching `marketplace.endpoint` at
runtime. The brief already documented that sandbox is unreliable for
placement/transportation logic; real testing happens with tiny live shipments.
If `settings.SP_API_ENVIRONMENT == 'SANDBOX'` we log a warning and fall
through to production rather than silently misroute requests.

Method-signature quirks (verified against v2.1.8 source):

    create_inbound_plan(self, **kwargs)
        ^ body fields are splatted into kwargs, NOT wrapped in body=

    set_packing_information(self, inboundPlanId, **kwargs)
        ^ inboundPlanId positional, rest as kwargs

    get_labels(self, shipment_id, **kwargs)
        ^ shipment_id positional; PageType/LabelType as kwargs

The wrapper method signatures below mirror saleweaver's so callers don't
have to juggle this.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from django.conf import settings
from django.utils import timezone

from fba_shipments.models import FBAAPICall, FBAShipmentPlan

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# saleweaver imports                                                          #
# --------------------------------------------------------------------------- #
#
# We guard the imports so that other parts of the module (e.g. models, admin,
# management commands) keep working even if the library is missing. Every
# method that actually talks to SP-API raises a clear ImportError instead.

try:
    from sp_api.api import FulfillmentInboundV20240320
    from sp_api.api import FulfillmentInboundV0  # documented fallback; unused by default
    from sp_api.base import Marketplaces
    from sp_api.base.exceptions import (
        SellingApiException,
        SellingApiRequestThrottledException,
    )
    SP_API_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive
    SP_API_AVAILABLE = False
    FulfillmentInboundV20240320 = None  # type: ignore[assignment]
    FulfillmentInboundV0 = None  # type: ignore[assignment]
    Marketplaces = None  # type: ignore[assignment]
    SellingApiException = Exception  # type: ignore[assignment,misc]
    SellingApiRequestThrottledException = Exception  # type: ignore[assignment,misc]


# --------------------------------------------------------------------------- #
# Marketplace maps                                                            #
# --------------------------------------------------------------------------- #

# Amazon marketplace IDs used by `createInboundPlan.destinationMarketplaces`.
MARKETPLACE_TO_AMAZON_ID: dict[str, str] = {
    'UK': 'A1F83G8C2ARO7P',
    'US': 'ATVPDKIKX0DER',
    'CA': 'A2EUQ1WTGCTBG2',
    'AU': 'A39IBJ37TRP1C6',
    'DE': 'A1PA6795UKMFR9',
}

# Map a manufacture-app marketplace code to the saleweaver Marketplaces enum
# value. `UK` is a valid alias for `GB` on the saleweaver enum in 2.1.8; we
# prefer `UK` for consistency with the rest of the manufacture app.
_MARKETPLACE_ENUM_NAMES: dict[str, str] = {
    'UK': 'UK',
    'US': 'US',
    'CA': 'CA',
    'AU': 'AU',
    'DE': 'DE',
}


def _get_marketplace_enum(marketplace_code: str):
    if not SP_API_AVAILABLE:
        raise ImportError(
            'python-amazon-sp-api is not installed. Add it to requirements.txt.'
        )
    enum_name = _MARKETPLACE_ENUM_NAMES.get(marketplace_code, marketplace_code)
    return getattr(Marketplaces, enum_name)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

# How long to sleep between `getInboundOperationStatus` polls in the synchronous
# helper. The state machine in Phase 2.3 uses one-poll-per-task-invocation
# instead of this loop, so POLL_INTERVAL_SECONDS only affects tests and scripts.
POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 300  # 5 minutes per async op

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2


def _safe_json(obj: Any) -> Any:
    """
    Coerce a potentially non-JSON-serialisable object (Decimal, datetime, etc.)
    into something JSONField can store, by round-tripping through json with
    default=str. Idempotent for already-serialisable values.
    """
    if obj is None:
        return None
    try:
        return json.loads(json.dumps(obj, default=str))
    except (TypeError, ValueError):
        # Last-ditch: stringify everything
        return {'__unserialisable__': str(obj)}


def _extract_payload(response: Any) -> Any:
    """
    Normalise saleweaver ApiResponse (or a raw dict) to its payload.
    saleweaver returns an `ApiResponse` with `.payload` for most calls; tests
    sometimes pass raw dicts in so we accept both.
    """
    if hasattr(response, 'payload'):
        return response.payload
    return response


def _extract_operation_id(payload: Any) -> str:
    if isinstance(payload, dict):
        return payload.get('operationId', '') or ''
    return ''


# --------------------------------------------------------------------------- #
# Client                                                                      #
# --------------------------------------------------------------------------- #


class FBAInboundClient:
    """
    Wrapper around the saleweaver FulfillmentInboundV20240320 client.

    Responsibilities:
      * Construct the underlying client with the right marketplace + credentials
      * Log every request/response to FBAAPICall for audit/debugging
      * Retry on throttle with exponential backoff
      * Provide typed method wrappers so the state machine doesn't handle
        raw dicts
      * Supply a `poll_operation()` helper for tests / one-off scripts
    """

    def __init__(
        self,
        marketplace_code: str,
        plan: FBAShipmentPlan | None = None,
        *,
        _client=None,
    ) -> None:
        """
        Args:
            marketplace_code: 'UK' / 'US' / 'CA' / 'AU' / 'DE'.
            plan: optional FBAShipmentPlan instance that this client is serving;
                  every FBAAPICall row will be linked to it for easy debugging.
            _client: test-injection hook. Passing a mock here skips saleweaver
                     instantiation entirely so unit tests don't need live creds.
        """
        self.marketplace_code = marketplace_code
        self.plan = plan

        if _client is not None:
            self._client = _client
            return

        if not SP_API_AVAILABLE:
            raise ImportError(
                'python-amazon-sp-api is not installed. Add it to requirements.txt.'
            )

        environment = getattr(settings, 'SP_API_ENVIRONMENT', 'PRODUCTION')
        if environment == 'SANDBOX':
            logger.warning(
                'SP_API_ENVIRONMENT=SANDBOX requested but saleweaver 2.x has no '
                'clean sandbox toggle. Falling back to PRODUCTION. See the '
                'fba_shipments.services.sp_api_client module docstring.'
            )

        credentials = self._build_credentials(marketplace_code)
        self._client = FulfillmentInboundV20240320(
            marketplace=_get_marketplace_enum(marketplace_code),
            credentials=credentials,
        )

    @staticmethod
    def _build_credentials(marketplace_code: str) -> dict:
        """
        Compose the credentials dict, using the per-marketplace refresh token
        from `settings.SP_API_REFRESH_TOKENS` when available. Matches the
        pattern used by `barcodes.services.sp_api_sync`.
        """
        base = dict(getattr(settings, 'SP_API_CREDENTIALS', {}) or {})
        refresh_tokens = getattr(settings, 'SP_API_REFRESH_TOKENS', {}) or {}
        override = refresh_tokens.get(marketplace_code)
        if override:
            base['refresh_token'] = override
        return base

    # ------------------------------------------------------------------ #
    # Core call / log / retry machinery                                  #
    # ------------------------------------------------------------------ #

    def _call(
        self,
        operation_name: str,
        method_name: str,
        *args,
        **kwargs,
    ) -> Any:
        """
        Execute a single SP-API call with logging, retry, and audit.

        `operation_name` is the human-readable name used in FBAAPICall (e.g.
        'createInboundPlan'). `method_name` is the actual saleweaver method
        name (e.g. 'create_inbound_plan'). The remaining args/kwargs are
        splatted into the saleweaver call.

        Returns the `.payload` of the response on success (or the raw
        response if it has no `.payload`).

        Raises the underlying exception on final failure (after retries).
        """
        start = time.monotonic()
        safe_args = _safe_json(list(args)) if args else None
        safe_kwargs = _safe_json(kwargs) if kwargs else None
        # Combine args + kwargs into a single request-body blob for the audit
        # log. Callers rarely pass positional args, but we keep both.
        request_body: dict[str, Any] = {}
        if safe_args:
            request_body['args'] = safe_args
        if safe_kwargs:
            request_body.update(safe_kwargs)
        if not request_body:
            request_body = None  # type: ignore[assignment]

        backoff = INITIAL_BACKOFF_SECONDS
        last_exception: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                method = getattr(self._client, method_name)
                response = method(*args, **kwargs)
                payload = _extract_payload(response)

                FBAAPICall.objects.create(
                    plan=self.plan,
                    operation_name=operation_name,
                    request_body=request_body,
                    response_status=200,
                    response_body=_safe_json(payload),
                    operation_id=_extract_operation_id(payload),
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
                return payload

            except SellingApiRequestThrottledException as exc:
                last_exception = exc
                logger.warning(
                    'SP-API throttled on %s, attempt %d/%d, sleeping %ds',
                    operation_name, attempt + 1, MAX_RETRIES, backoff,
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            except SellingApiException as exc:
                # saleweaver 2.1.8 attrs: .code (HTTP), .error (list of error dicts),
                # .amzn_code, .headers, .message. Note: singular `.error`, not `.errors`.
                # `str(exc)` is empty on this class, so build a useful message
                # from `.message` / `.amzn_code` / first error dict.
                err_list = getattr(exc, 'error', None) or []
                amzn_code = getattr(exc, 'amzn_code', '') or ''
                msg = getattr(exc, 'message', '') or ''
                if not msg and err_list and isinstance(err_list[0], dict):
                    msg = err_list[0].get('message', '') or ''
                error_message = (
                    f'{amzn_code}: {msg}' if amzn_code and msg
                    else msg or amzn_code or str(exc) or exc.__class__.__name__
                )
                FBAAPICall.objects.create(
                    plan=self.plan,
                    operation_name=operation_name,
                    request_body=request_body,
                    response_status=getattr(exc, 'code', 0) or 0,
                    response_body=_safe_json({
                        'errors': err_list,
                        'amzn_code': amzn_code,
                    }),
                    duration_ms=int((time.monotonic() - start) * 1000),
                    error_message=error_message,
                )
                raise

        # Retries exhausted for throttling.
        FBAAPICall.objects.create(
            plan=self.plan,
            operation_name=operation_name,
            request_body=request_body,
            response_status=429,
            error_message=(
                f'Throttled, all {MAX_RETRIES} retries exhausted: {last_exception}'
            ),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        assert last_exception is not None  # for type-checkers
        raise last_exception

    # ------------------------------------------------------------------ #
    # v2024-03-20 workflow operations                                    #
    # ------------------------------------------------------------------ #
    #
    # Each wrapper is deliberately thin: it exists so callers get IDE
    # completion, so arg names are documented, and so operation_name is
    # consistent in the audit log. The callers should not have to know
    # about saleweaver's method-name conventions.

    def create_inbound_plan(self, body: dict) -> dict:
        """POST /fba/inbound/2024-03-20/inboundPlans — async, returns operationId."""
        return self._call('createInboundPlan', 'create_inbound_plan', **body)

    def cancel_inbound_plan(self, inbound_plan_id: str) -> dict:
        """PUT /fba/inbound/2024-03-20/inboundPlans/{}/cancellation — async."""
        return self._call(
            'cancelInboundPlan',
            'cancel_inbound_plan',
            inbound_plan_id,
        )

    def get_operation_status(self, operation_id: str) -> dict:
        """GET /fba/inbound/2024-03-20/operations/{operationId}."""
        return self._call(
            'getInboundOperationStatus',
            'get_inbound_operation_status',
            operation_id,
        )

    def generate_packing_options(self, inbound_plan_id: str) -> dict:
        return self._call(
            'generatePackingOptions',
            'generate_packing_options',
            inbound_plan_id,
        )

    def list_packing_options(self, inbound_plan_id: str) -> dict:
        return self._call(
            'listPackingOptions',
            'list_packing_options',
            inbound_plan_id,
        )

    def set_packing_information(self, inbound_plan_id: str, body: dict) -> dict:
        """
        POST /fba/inbound/2024-03-20/inboundPlans/{}/packingInformation — async.

        saleweaver signature: set_packing_information(self, inboundPlanId, **kwargs)
        """
        return self._call(
            'setPackingInformation',
            'set_packing_information',
            inbound_plan_id,
            **body,
        )

    def confirm_packing_option(self, inbound_plan_id: str, packing_option_id: str) -> dict:
        return self._call(
            'confirmPackingOption',
            'confirm_packing_option',
            inbound_plan_id,
            packing_option_id,
        )

    def generate_placement_options(
        self,
        inbound_plan_id: str,
        body: dict | None = None,
    ) -> dict:
        return self._call(
            'generatePlacementOptions',
            'generate_placement_options',
            inbound_plan_id,
            **(body or {}),
        )

    def list_placement_options(self, inbound_plan_id: str) -> dict:
        return self._call(
            'listPlacementOptions',
            'list_placement_options',
            inbound_plan_id,
        )

    def confirm_placement_option(
        self,
        inbound_plan_id: str,
        placement_option_id: str,
    ) -> dict:
        return self._call(
            'confirmPlacementOption',
            'confirm_placement_option',
            inbound_plan_id,
            placement_option_id,
        )

    def generate_transportation_options(
        self,
        inbound_plan_id: str,
        body: dict,
    ) -> dict:
        return self._call(
            'generateTransportationOptions',
            'generate_transportation_options',
            inbound_plan_id,
            **body,
        )

    def list_transportation_options(
        self,
        inbound_plan_id: str,
        placement_option_id: str | None = None,
    ) -> dict:
        kwargs: dict[str, Any] = {}
        if placement_option_id:
            kwargs['placementOptionId'] = placement_option_id
        return self._call(
            'listTransportationOptions',
            'list_transportation_options',
            inbound_plan_id,
            **kwargs,
        )

    def generate_delivery_window_options(
        self,
        inbound_plan_id: str,
        shipment_id: str,
    ) -> dict:
        return self._call(
            'generateDeliveryWindowOptions',
            'generate_delivery_window_options',
            inbound_plan_id,
            shipment_id,
        )

    def list_delivery_window_options(
        self,
        inbound_plan_id: str,
        shipment_id: str,
    ) -> dict:
        return self._call(
            'listDeliveryWindowOptions',
            'list_delivery_window_options',
            inbound_plan_id,
            shipment_id,
        )

    def confirm_transportation_options(
        self,
        inbound_plan_id: str,
        body: dict,
    ) -> dict:
        return self._call(
            'confirmTransportationOptions',
            'confirm_transportation_options',
            inbound_plan_id,
            **body,
        )

    def list_inbound_plans(self, **filters) -> dict:
        """Used by the reconciliation task (Phase 2.6) to detect externally-cancelled plans."""
        return self._call(
            'listInboundPlans',
            'list_inbound_plans',
            **filters,
        )

    def get_labels(
        self,
        shipment_confirmation_id: str,
        *,
        page_type: str = 'PackageLabel_Plain_Paper',
        label_type: str = 'UNIQUE',
    ) -> dict:
        """
        GET /fba/inbound/2024-03-20/shipments/{shipmentId}/labels

        In saleweaver 2.1.8 `FulfillmentInboundV20240320.get_labels` is a real
        method — the brief's requirement to fall back to v0 no longer applies.
        If Amazon ever 404s this for a specific shipment, use `get_labels_v0`
        as a manual escape hatch.
        """
        return self._call(
            'getLabels',
            'get_labels',
            shipment_confirmation_id,
            PageType=page_type,
            LabelType=label_type,
        )

    # ------------------------------------------------------------------ #
    # v0 fallback — not wired by default                                 #
    # ------------------------------------------------------------------ #

    def get_labels_v0(
        self,
        shipment_confirmation_id: str,
        *,
        page_type: str = 'PackageLabel_Plain_Paper',
        label_type: str = 'UNIQUE',
    ) -> dict:
        """
        Manual escape hatch: calls `/fba/inbound/v0/shipments/{}/labels`.

        Instantiates a one-shot `FulfillmentInboundV0` client. Only use if
        Amazon 404s the v2024 labels endpoint for a specific shipment. The
        call is logged as operation 'getLabels (v0)' in FBAAPICall so it's
        easy to spot in the audit log.
        """
        if not SP_API_AVAILABLE:
            raise ImportError(
                'python-amazon-sp-api is not installed. Add it to requirements.txt.'
            )
        v0_client = FulfillmentInboundV0(
            marketplace=_get_marketplace_enum(self.marketplace_code),
            credentials=self._build_credentials(self.marketplace_code),
        )
        # Temporarily swap the underlying client for the _call machinery.
        saved = self._client
        self._client = v0_client
        try:
            return self._call(
                'getLabels (v0)',
                'get_labels',
                shipment_confirmation_id,
                PageType=page_type,
                LabelType=label_type,
            )
        finally:
            self._client = saved

    # ------------------------------------------------------------------ #
    # Polling helper                                                     #
    # ------------------------------------------------------------------ #

    def poll_operation(
        self,
        operation_id: str,
        timeout: int = POLL_TIMEOUT_SECONDS,
        interval: int = POLL_INTERVAL_SECONDS,
    ) -> dict:
        """
        Poll `getInboundOperationStatus` until SUCCESS or FAILED.

        Returns the final payload on SUCCESS. Raises:
          * RuntimeError on FAILED (with operationProblems in the message)
          * TimeoutError on timeout

        NOTE: this is a SYNCHRONOUS polling loop that blocks the caller for
        up to `timeout` seconds. The Phase 2.3 state machine does NOT use
        this — it uses check-once-and-reenqueue so a single worker slot is
        never blocked for minutes. This helper exists for tests and one-off
        scripts only.
        """
        if timeout <= 0:
            raise ValueError('timeout must be positive')
        deadline = time.monotonic() + timeout

        while True:
            payload = self.get_operation_status(operation_id)
            status = (payload or {}).get('operationStatus', 'IN_PROGRESS')

            if status == 'SUCCESS':
                return payload
            if status == 'FAILED':
                errors = (payload or {}).get('operationProblems', [])
                raise RuntimeError(
                    f'Operation {operation_id} failed: {errors}'
                )

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f'Operation {operation_id} still {status} after {timeout}s'
                )
            time.sleep(interval)
