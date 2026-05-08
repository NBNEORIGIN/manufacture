# sales_velocity — Xero integration notes

Manufacture owns the Xero OAuth connection for the cluster. Other
services (Ledger primarily) consume invoice data via the
`/api/xero/...` endpoints rather than each running their own OAuth.

## After widening the Xero scope (2026-05-08): re-consent

The `XERO_SCOPES` list in `adapters/xero.py` was widened from
`accounting.invoices.read` to `accounting.transactions.read` +
`accounting.contacts.read` so that Ledger can pull ACCPAY (bills) data,
not just ACCREC (sales). Existing refresh tokens were issued under the
old narrower scope and won't grant access to ACCPAY endpoints — they
must be re-issued via the consent flow.

### Playbook

1. Deploy the scope change (push to `main` triggers Hetzner deploy).
2. Visit `https://app.nbnesigns.co.uk/admin/oauth/xero/connect` while
   logged in as a staff user.
3. Xero shows the consent screen with the new scopes listed. Approve.
4. Verify by hitting `/api/xero/health`:

   ```bash
   curl -H "X-API-Key: $CAIRN_API_KEY" \
     https://app.nbnesigns.co.uk/api/xero/health
   ```

   Expected: `connected: true`, `tenant_name` populated, `scopes`
   includes `accounting.transactions.read` and
   `accounting.contacts.read`.

### What happens before re-consent

- `fetch_invoice_revenue()` (the legacy aggregate path) keeps working
  on the old token until it expires (~30 minutes from issue).
- `fetch_invoices(invoice_type='ACCPAY', ...)` will fail with HTTP 403
  (scope insufficient) because the existing token doesn't grant
  ACCPAY access.
- Token refresh attempts after the access token expires either succeed
  with old scopes (if Xero hasn't yet processed the dev-app config
  update) or fail. Either way, re-consent is required to get tokens
  with the widened scopes.

There is no risk to production data — Xero is read-only on this
integration and stale tokens never write.

## Endpoints

### `GET /api/xero/health`

Returns connection state. Doesn't trigger a token refresh.

### `GET /api/xero/invoices/?type=ACCREC&days=30`

Per-invoice rows (NOT aggregated). Use `type=ACCREC` for sales,
`type=ACCPAY` for bills. Cached 5 min per (type, days) tuple to avoid
hammering Xero when Ledger polls every few minutes.

Auth: `Authorization: Bearer <CAIRN_API_KEY>` or `X-API-Key:
<CAIRN_API_KEY>` or a logged-in Django session.

Response shape: see `sales_velocity/adapters/xero.py::fetch_invoices`
docstring.
