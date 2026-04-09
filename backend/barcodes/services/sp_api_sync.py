"""
SP-API FNSKU sync service.

NOTE on library method names: saleweaver's python-amazon-sp-api has had renames
across versions. Before using in production, verify the exact method name by
running a single call in the Django shell:

    from sp_api.api import FBAInventory
    help(FBAInventory)

Also verify where the pagination token lives in the response — some versions
put it in response.next_token, others in response.payload['pagination']['nextToken'].
The code below checks both locations defensively.
"""
from django.conf import settings
from django.utils import timezone

from products.models import SKU
from barcodes.models import ProductBarcode

try:
    from sp_api.api import FBAInventory
    from sp_api.base import Marketplaces
    SP_API_AVAILABLE = True
except ImportError:
    SP_API_AVAILABLE = False

MARKETPLACE_MAP = {
    'UK': 'UK',
    'US': 'US',
    'CA': 'CA',
    'AU': 'AU',
    'DE': 'DE',
}


def _get_marketplace(code: str):
    if not SP_API_AVAILABLE:
        raise ImportError("python-amazon-sp-api is not installed. Add it to requirements.txt.")
    return getattr(Marketplaces, code)


def sync_fnskus_for_marketplace(marketplace_code: str) -> dict:
    """
    Pull all FNSKUs for the given marketplace and upsert ProductBarcode rows.

    Returns: {'created': int, 'updated': int, 'unmatched_skus': list[str]}
    """
    client = FBAInventory(
        credentials=settings.SP_API_CREDENTIALS,
        marketplace=_get_marketplace(marketplace_code),
    )

    created = 0
    updated = 0
    unmatched = []
    next_token = None

    while True:
        kwargs = {'details': True}
        if next_token:
            kwargs['NextToken'] = next_token

        try:
            response = client.get_inventory_summaries(**kwargs)
        except Exception as exc:
            # Re-raise throttle exceptions so the caller can back off
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
