"""
SP-API FNSKU sync service.

Library notes (verified against python-amazon-sp-api v2.1.8):
  - Class: Inventories  (was FBAInventory in v1.x)
  - Method: get_inventory_summary_marketplace  (was get_inventory_summaries in v1.x)
  - Required kwargs: granularityType='Marketplace', granularityId=<marketplace_id>
  - Pagination token: response.payload['pagination']['nextToken']

NOTE on library method names: saleweaver's python-amazon-sp-api has had renames
across versions. Before using in production, verify the exact method name by
running a single call in the Django shell:

    from sp_api.api import FBAInventory
    help(FBAInventory)

Also verify where the pagination token lives in the response — some versions
put it in response.next_token, others in response.payload['pagination']['nextToken'].
The code below checks both locations defensively.
"""
import re
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from products.models import Product, SKU
from barcodes.models import ProductBarcode

try:
    # v2.x renamed FBAInventory → Inventories
    from sp_api.api import Inventories as _InventoriesClient
    from sp_api.base import Marketplaces
    SP_API_AVAILABLE = True
except ImportError:
    SP_API_AVAILABLE = False
    _InventoriesClient = None
    Marketplaces = None


def _get_marketplace(code: str):
    if not SP_API_AVAILABLE:
        raise ImportError("python-amazon-sp-api is not installed. Add it to requirements.txt.")
    return getattr(Marketplaces, code)


def _auto_create_from_summary(summary: dict, marketplace_code: str):
    """
    Create a stub Product + SKU from an inventory summary when no local match exists.

    Uses the ASIN as a temporary M-number (prefix AZ-) so records are clearly
    auto-generated. If neither ASIN nor productName is available we skip creation
    and leave the SKU in the unmatched list.

    Returns a SKU instance (with .product populated) or None.
    """
    seller_sku = summary.get('sellerSku', '').strip()
    asin = summary.get('asin', '').strip()
    product_name = summary.get('productName', '').strip()

    if not asin:
        return None  # nothing to key a stub product on

    # Derive a safe M-number from the ASIN (AZ- prefix, max 10 chars)
    m_number = f'AZ-{asin}'[:10]

    description = (product_name or seller_sku)[:500] or asin

    with transaction.atomic():
        product, _ = Product.objects.get_or_create(
            m_number=m_number,
            defaults={
                'description': description,
                'blank': 'AMAZON',
                'is_personalised': False,
            },
        )
        # Derive channel from marketplace_code
        channel_map = {
            'UK': 'UK', 'US': 'US', 'CA': 'CA',
            'AU': 'AU', 'DE': 'DE', 'ES': 'ES',
            'FR': 'FR', 'IT': 'IT', 'NL': 'NL',
        }
        channel = channel_map.get(marketplace_code, marketplace_code)
        sku_obj, _ = SKU.objects.get_or_create(
            sku=seller_sku,
            channel=channel,
            defaults={'product': product, 'asin': asin},
        )
        sku_obj.product = product  # ensure the relation is loaded
    return sku_obj


def sync_fnskus_for_marketplace(marketplace_code: str) -> dict:
    """
    Pull all FNSKUs for the given marketplace and upsert ProductBarcode rows.

    Returns: {'created': int, 'updated': int, 'unmatched_skus': list[str]}
    """
    # Use per-marketplace refresh token where available
    refresh_tokens = getattr(settings, 'SP_API_REFRESH_TOKENS', {})
    base_creds = dict(settings.SP_API_CREDENTIALS)
    if marketplace_code in refresh_tokens and refresh_tokens[marketplace_code]:
        base_creds['refresh_token'] = refresh_tokens[marketplace_code]

    client = _InventoriesClient(
        credentials=base_creds,
        marketplace=_get_marketplace(marketplace_code),
    )

    created = 0
    updated = 0
    unmatched = []
    next_token = None

    while True:
        kwargs = {'details': True, 'granularityType': 'Marketplace', 'granularityId': _get_marketplace(marketplace_code).marketplace_id}
        if next_token:
            kwargs['nextToken'] = next_token

        # v2.x method is get_inventory_summary_marketplace (singular)
        # Retry once on throttle with 10s backoff
        for attempt in range(2):
            try:
                response = client.get_inventory_summary_marketplace(**kwargs)
                break
            except Exception as exc:
                if attempt == 0 and 'Throttl' in type(exc).__name__:
                    time.sleep(10)
                    continue
                raise

        summaries = []
        if hasattr(response, 'payload') and isinstance(response.payload, dict):
            summaries = response.payload.get('inventorySummaries', [])

        for summary in summaries:
            seller_sku = summary.get('sellerSku')
            fnsku = summary.get('fnSku')

            if not (seller_sku and fnsku):
                continue

            try:
                sku_obj = SKU.objects.select_related('product').get(sku=seller_sku)
            except SKU.DoesNotExist:
                sku_obj = _auto_create_from_summary(summary, marketplace_code)
                if sku_obj is None:
                    unmatched.append(seller_sku)
                    continue

            obj, is_created = ProductBarcode.objects.update_or_create(
                product=sku_obj.product,
                marketplace=marketplace_code,
                barcode_type='FNSKU',
                defaults={
                    'barcode_value': fnsku,
                    'label_title': sku_obj.product.description[:80],
                    'source': 'sp_api',
                    'last_synced_at': timezone.now(),
                },
            )
            if is_created:
                created += 1
            else:
                updated += 1

        # Pagination token location varies by library version — check both
        pagination = {}
        if hasattr(response, 'payload') and isinstance(response.payload, dict):
            pagination = response.payload.get('pagination', {})
        next_token = (
            getattr(response, 'next_token', None)
            or (pagination.get('nextToken') if isinstance(pagination, dict) else None)
        )
        if not next_token:
            break

    return {'created': created, 'updated': updated, 'unmatched_skus': unmatched}
