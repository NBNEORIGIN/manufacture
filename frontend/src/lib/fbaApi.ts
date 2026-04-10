/**
 * Typed API client for the FBA Shipment Automation module.
 *
 * All endpoints live under /api/fba/ in the backend (see
 * backend/fba_shipments/urls.py). Response types mirror the DRF
 * serializers in backend/fba_shipments/serializers.py.
 *
 * Kept separate from src/lib/api.ts so the legacy manual /shipments
 * module (still used for non-Amazon exports) remains untouched.
 */

import { api } from '@/lib/api'

// --------------------------------------------------------------------------- //
// Status vocabulary                                                           //
// --------------------------------------------------------------------------- //

export const FBA_STATUSES = [
  'draft',
  'items_added',
  'plan_creating',
  'plan_created',
  'packing_options_generating',
  'packing_options_ready',     // paused — user picks packing option
  'packing_info_setting',
  'packing_info_set',
  'packing_option_confirming',
  'packing_option_confirmed',
  'placement_options_generating',
  'placement_options_ready',   // paused — user picks placement option
  'placement_option_confirming',
  'placement_option_confirmed',
  'transport_options_generating',
  'transport_options_ready',
  'delivery_window_generating',
  'delivery_window_ready',
  'transport_confirming',
  'transport_confirmed',
  'labels_ready',              // paused — waiting for manual dispatch
  'ready_to_ship',
  'dispatched',
  'delivered',
  'error',
  'cancelled',
] as const

export type FBAStatus = (typeof FBA_STATUSES)[number]

export const PAUSED_STATUSES = new Set<FBAStatus>([
  'packing_options_ready',
  'placement_options_ready',
  'labels_ready',
  'ready_to_ship',
])

export const TERMINAL_STATUSES = new Set<FBAStatus>([
  'delivered',
  'cancelled',
])

// --------------------------------------------------------------------------- //
// Types                                                                       //
// --------------------------------------------------------------------------- //

export interface FBAPlanListItem {
  id: number
  name: string
  marketplace: string
  status: FBAStatus
  inbound_plan_id: string | null
  item_count: number
  box_count: number
  shipment_count: number
  is_paused: boolean
  is_terminal: boolean
  created_at: string
  updated_at: string
}

export interface FBAPlanItem {
  id: number
  sku: number
  sku_code: string
  m_number: string
  product_description: string
  quantity: number
  msku: string
  fnsku: string
  label_owner: string
  prep_owner: string
  created_at: string
  updated_at: string
}

export interface FBABoxContent {
  id: number
  plan_item: number
  msku: string
  quantity: number
}

export interface FBABox {
  id: number
  plan: number
  shipment: number | null
  box_number: number
  length_cm: string
  width_cm: string
  height_cm: string
  weight_kg: string
  amazon_box_id: string | null
  contents: FBABoxContent[]
  created_at: string
  updated_at: string
}

export interface FBAShipment {
  id: number
  shipment_id: string
  shipment_confirmation_id: string
  destination_fc: string
  labels_url: string
  labels_fetched_at: string | null
  carrier_name: string
  tracking_number: string
  dispatched_at: string | null
  created_at: string
  updated_at: string
}

export interface FBAAPICallSummary {
  id: number
  operation_name: string
  response_status: number
  operation_id: string
  duration_ms: number
  error_message: string
  created_at: string
}

export interface FBAAPICallDetail extends FBAAPICallSummary {
  request_body: string
  response_body: string
}

export interface FBAErrorLogEntry {
  step: string
  message: string
  exc_type?: string
  at?: string
}

export interface FBAPlanDetail {
  id: number
  name: string
  marketplace: string
  ship_from_address: Record<string, unknown>
  status: FBAStatus
  inbound_plan_id: string | null
  selected_packing_option_id: string
  selected_placement_option_id: string
  selected_transportation_option_id: string
  selected_delivery_window_id: string
  current_operation_id: string
  current_operation_started_at: string | null
  last_polled_at: string | null
  error_log: FBAErrorLogEntry[] | null
  packing_options_snapshot: { packingOptions?: PackingOptionSnapshot[] } | null
  placement_options_snapshot: { placementOptions?: PlacementOptionSnapshot[] } | null
  transportation_options_snapshot: Record<string, unknown> | null
  delivery_window_snapshot: Record<string, unknown> | null
  items: FBAPlanItem[]
  boxes: FBABox[]
  shipments: FBAShipment[]
  recent_api_calls: FBAAPICallSummary[]
  is_paused: boolean
  is_terminal: boolean
  created_at: string
  updated_at: string
}

// Snapshot shapes are loosely typed because Amazon evolves them.
// We pull the fields we need for rendering + pass the ID through on select.
export interface PackingOptionSnapshot {
  packingOptionId: string
  status?: string
  fees?: { value?: { amount?: string | number; code?: string } }[]
  discounts?: unknown[]
  expiration?: string
}

export interface PlacementOptionSnapshot {
  placementOptionId: string
  status?: string
  fees?: { value?: { amount?: string | number; code?: string } }[]
  shipmentIds?: string[]
  expiration?: string
}

export interface PreflightResult {
  marketplace: string
  active_skus: number
  with_fnsku: number
  with_dims: number
  fully_ready: number
  ready: boolean
  missing_fnsku: { sku: string; m_number: string }[]
  missing_dims: { m_number: string; description: string }[]
  prep_category_reminder: string
}

// --------------------------------------------------------------------------- //
// Error handling                                                              //
// --------------------------------------------------------------------------- //

export class FBAApiError extends Error {
  status: number
  body: Record<string, unknown>

  constructor(status: number, body: Record<string, unknown>, message: string) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let body: Record<string, unknown> = {}
    try {
      body = await r.json()
    } catch {
      // non-JSON error
    }
    const msg =
      (body.detail as string) ||
      (body.error as string) ||
      (Array.isArray(body.errors) ? (body.errors as string[]).join('; ') : '') ||
      `HTTP ${r.status}`
    throw new FBAApiError(r.status, body, msg)
  }
  // Some endpoints return 204 No Content
  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}

// --------------------------------------------------------------------------- //
// Plans                                                                       //
// --------------------------------------------------------------------------- //

export async function listFbaPlans(params: {
  marketplace?: string
  status?: string
} = {}): Promise<{ results: FBAPlanListItem[]; count: number }> {
  const qs = new URLSearchParams()
  if (params.marketplace) qs.set('marketplace', params.marketplace)
  if (params.status) qs.set('status', params.status)
  qs.set('page_size', '100')
  const r = await api(`/api/fba/plans/?${qs}`)
  const data = await handle<{ results?: FBAPlanListItem[]; count?: number } | FBAPlanListItem[]>(r)
  if (Array.isArray(data)) {
    return { results: data, count: data.length }
  }
  return { results: data.results || [], count: data.count || 0 }
}

export async function getFbaPlan(id: number): Promise<FBAPlanDetail> {
  const r = await api(`/api/fba/plans/${id}/`)
  return handle<FBAPlanDetail>(r)
}

export async function createFbaPlan(payload: {
  name: string
  marketplace: string
  ship_from_address?: Record<string, unknown>
}): Promise<FBAPlanDetail> {
  const r = await api('/api/fba/plans/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle<FBAPlanDetail>(r)
}

export async function patchFbaPlan(
  id: number,
  payload: Partial<{ name: string; ship_from_address: Record<string, unknown> }>,
): Promise<FBAPlanDetail> {
  const r = await api(`/api/fba/plans/${id}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle<FBAPlanDetail>(r)
}

export async function cancelFbaPlan(id: number): Promise<void> {
  const r = await api(`/api/fba/plans/${id}/`, { method: 'DELETE' })
  if (!r.ok && r.status !== 204) {
    return handle<void>(r)
  }
}

// --------------------------------------------------------------------------- //
// Items                                                                       //
// --------------------------------------------------------------------------- //

export async function addPlanItems(
  planId: number,
  items: { sku_id: number; quantity: number }[],
): Promise<FBAPlanItem[]> {
  const r = await api(`/api/fba/plans/${planId}/items/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  })
  return handle<FBAPlanItem[]>(r)
}

export async function removePlanItem(planId: number, itemId: number): Promise<void> {
  const r = await api(`/api/fba/plans/${planId}/items/${itemId}/`, {
    method: 'DELETE',
  })
  if (!r.ok && r.status !== 204) return handle<void>(r)
}

// --------------------------------------------------------------------------- //
// Boxes                                                                       //
// --------------------------------------------------------------------------- //

export interface NewBoxPayload {
  box_number: number
  length_cm: string | number
  width_cm: string | number
  height_cm: string | number
  weight_kg: string | number
  contents: { plan_item_id: number; quantity: number }[]
}

export async function addBox(planId: number, payload: NewBoxPayload): Promise<FBABox> {
  const r = await api(`/api/fba/plans/${planId}/boxes/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle<FBABox>(r)
}

export async function updateBox(
  planId: number,
  boxId: number,
  payload: Partial<Omit<NewBoxPayload, 'contents'>>,
): Promise<FBABox> {
  const r = await api(`/api/fba/plans/${planId}/boxes/${boxId}/`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle<FBABox>(r)
}

export async function deleteBox(planId: number, boxId: number): Promise<void> {
  const r = await api(`/api/fba/plans/${planId}/boxes/${boxId}/`, {
    method: 'DELETE',
  })
  if (!r.ok && r.status !== 204) return handle<void>(r)
}

// --------------------------------------------------------------------------- //
// Submit / workflow actions                                                   //
// --------------------------------------------------------------------------- //

export async function submitPlan(planId: number): Promise<FBAPlanDetail> {
  const r = await api(`/api/fba/plans/${planId}/submit/`, { method: 'POST' })
  return handle<FBAPlanDetail>(r)
}

export async function pickPackingOption(
  planId: number,
  packingOptionId: string,
): Promise<FBAPlanDetail> {
  const r = await api(`/api/fba/plans/${planId}/pick-packing-option/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ packing_option_id: packingOptionId }),
  })
  return handle<FBAPlanDetail>(r)
}

export async function pickPlacementOption(
  planId: number,
  placementOptionId: string,
): Promise<FBAPlanDetail> {
  const r = await api(`/api/fba/plans/${planId}/pick-placement-option/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ placement_option_id: placementOptionId }),
  })
  return handle<FBAPlanDetail>(r)
}

export async function retryPlan(
  planId: number,
  rewindTo?: FBAStatus,
): Promise<FBAPlanDetail> {
  const r = await api(`/api/fba/plans/${planId}/retry/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(rewindTo ? { rewind_to: rewindTo } : {}),
  })
  return handle<FBAPlanDetail>(r)
}

// --------------------------------------------------------------------------- //
// Shipments                                                                   //
// --------------------------------------------------------------------------- //

export async function dispatchShipment(
  planId: number,
  shipmentPk: number,
  payload: { carrier_name: string; tracking_number: string },
): Promise<FBAShipment> {
  const r = await api(`/api/fba/plans/${planId}/shipments/${shipmentPk}/dispatch/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle<FBAShipment>(r)
}

/** Returns a blob URL for the labels PDF proxy endpoint. */
export async function downloadLabels(planId: number, shipmentPk?: number): Promise<Blob> {
  const qs = shipmentPk ? `?shipment_id=${shipmentPk}` : ''
  const r = await api(`/api/fba/plans/${planId}/labels/${qs}`)
  if (!r.ok) throw new FBAApiError(r.status, {}, `Labels fetch failed: HTTP ${r.status}`)
  return r.blob()
}

// --------------------------------------------------------------------------- //
// API call audit log                                                          //
// --------------------------------------------------------------------------- //

export async function listApiCalls(planId: number, limit = 50): Promise<FBAAPICallDetail[]> {
  const r = await api(`/api/fba/plans/${planId}/api-calls/?limit=${limit}`)
  return handle<FBAAPICallDetail[]>(r)
}

// --------------------------------------------------------------------------- //
// Preflight                                                                   //
// --------------------------------------------------------------------------- //

export async function preflight(marketplace: string): Promise<PreflightResult> {
  const r = await api(`/api/fba/preflight/?marketplace=${marketplace}`)
  return handle<PreflightResult>(r)
}
