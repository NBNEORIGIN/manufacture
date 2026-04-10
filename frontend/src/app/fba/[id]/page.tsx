'use client'

/**
 * FBA Shipment Automation — plan detail page.
 *
 * Everything a plan needs is driven from this single page:
 *
 *   • Status bar with refresh, cancel, retry controls
 *   • Items section (add SKU + qty, remove in draft)
 *   • Boxes section (add with contents, remove in draft/packing_options_ready)
 *   • Submit button (validates and kicks off the workflow)
 *   • Pick-packing-option / pick-placement-option forms (when paused)
 *   • Shipments section with dispatch form + labels download
 *   • Recent API calls audit log (collapsible)
 *
 * Polls the plan detail endpoint every 5s whenever the plan is in a
 * non-terminal, non-paused state so long-running workflow transitions
 * are visible without manual refresh.
 */

import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import {
  FBABox,
  FBAPlanDetail,
  FBAShipment,
  FBAApiError,
  PAUSED_STATUSES,
  TERMINAL_STATUSES,
  addBox,
  addPlanItems,
  cancelFbaPlan,
  deleteBox,
  dispatchShipment,
  downloadLabels,
  getFbaPlan,
  pickPackingOption,
  pickPlacementOption,
  removePlanItem,
  retryPlan,
  submitPlan,
} from '@/lib/fbaApi'

interface SKUListRow {
  id: number
  sku: string
  asin: string
  channel: string
  active: boolean
}

// --------------------------------------------------------------------------- //
// Page                                                                        //
// --------------------------------------------------------------------------- //

export default function FbaPlanDetailPage({ params }: { params: { id: string } }) {
  const planId = Number(params.id)

  const [plan, setPlan] = useState<FBAPlanDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setError('')
    try {
      const data = await getFbaPlan(planId)
      setPlan(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Load failed')
    } finally {
      setLoading(false)
    }
  }, [planId])

  useEffect(() => {
    load()
  }, [load])

  // Poll while workflow is in-flight
  useEffect(() => {
    if (!plan) return
    if (TERMINAL_STATUSES.has(plan.status)) return
    if (PAUSED_STATUSES.has(plan.status)) return
    if (plan.status === 'draft' || plan.status === 'error') return
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [plan, load])

  const flash = (m: string) => {
    setMessage(m)
    setTimeout(() => setMessage(''), 3000)
  }

  const runAction = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      flash(label)
      await load()
    } catch (e) {
      if (e instanceof FBAApiError) {
        // Submit validation returns {errors: [...]}
        const body = e.body as { errors?: string[]; detail?: string }
        const msg = body.errors?.join('; ') || body.detail || e.message
        setError(msg)
      } else {
        setError(e instanceof Error ? e.message : 'Action failed')
      }
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="text-gray-400">Loading…</p>
  }
  if (!plan) {
    return (
      <div>
        <a href="/fba" className="text-blue-600 hover:underline text-sm">
          ← Back to plans
        </a>
        <p className="mt-4 text-red-600">{error || 'Plan not found'}</p>
      </div>
    )
  }

  const isDraft = plan.status === 'draft'
  const isPaused = plan.is_paused
  const isTerminal = plan.is_terminal
  const isError = plan.status === 'error'
  const readyToShip = plan.status === 'ready_to_ship' || plan.status === 'dispatched'

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <a href="/fba" className="text-blue-600 hover:underline text-sm">
            ← Back to plans
          </a>
          <h2 className="text-2xl font-bold mt-1">
            {plan.name}{' '}
            <span className="text-gray-400 font-normal text-lg">#{plan.id}</span>
          </h2>
          <p className="text-sm text-gray-500">
            {plan.marketplace} ·{' '}
            {plan.inbound_plan_id ? (
              <span className="font-mono">{plan.inbound_plan_id}</span>
            ) : (
              'not yet submitted to Amazon'
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {message && (
            <span className="text-green-600 text-sm font-medium">{message}</span>
          )}
          <button
            onClick={load}
            className="text-sm px-3 py-1 border rounded hover:bg-gray-50"
          >
            Refresh
          </button>
          {!isTerminal && (
            <button
              onClick={() => {
                if (
                  confirm(
                    `Cancel plan #${plan.id}? This will attempt to cancel the inbound plan at Amazon if it has one.`,
                  )
                ) {
                  runAction('Cancelled', () => cancelFbaPlan(plan.id))
                }
              }}
              disabled={busy}
              className="text-sm px-3 py-1 border border-red-300 text-red-700 rounded hover:bg-red-50 disabled:opacity-60"
            >
              Cancel plan
            </button>
          )}
        </div>
      </div>

      <StatusBar plan={plan} />

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 mb-4 text-sm whitespace-pre-wrap">
          {error}
        </div>
      )}

      {isError && plan.error_log && plan.error_log.length > 0 && (
        <ErrorPanel
          plan={plan}
          busy={busy}
          onRetry={(rewindTo) =>
            runAction('Retrying…', () => retryPlan(plan.id, rewindTo))
          }
        />
      )}

      {/* PICK OPTIONS (paused states) */}
      {plan.status === 'packing_options_ready' &&
        !plan.selected_packing_option_id && (
          <PackingOptionsPicker
            plan={plan}
            busy={busy}
            onPick={(id) =>
              runAction('Packing option selected', () =>
                pickPackingOption(plan.id, id),
              )
            }
          />
        )}
      {plan.status === 'placement_options_ready' &&
        !plan.selected_placement_option_id && (
          <PlacementOptionsPicker
            plan={plan}
            busy={busy}
            onPick={(id) =>
              runAction('Placement option selected', () =>
                pickPlacementOption(plan.id, id),
              )
            }
          />
        )}

      <ItemsSection
        plan={plan}
        busy={busy}
        onReload={load}
        runAction={runAction}
      />

      <BoxesSection
        plan={plan}
        busy={busy}
        onReload={load}
        runAction={runAction}
      />

      {isDraft && (
        <div className="bg-white rounded-lg shadow p-4 mb-6 flex items-center justify-between">
          <div>
            <h3 className="font-semibold">Ready to submit?</h3>
            <p className="text-sm text-gray-500">
              Validation runs first — you&apos;ll see any missing FNSKUs, dims,
              or box content mismatches before anything is sent to Amazon.
            </p>
          </div>
          <button
            onClick={() => runAction('Submitted to workflow', () => submitPlan(plan.id))}
            disabled={busy}
            className="bg-blue-600 text-white px-6 py-2 rounded font-semibold hover:bg-blue-700 disabled:opacity-60"
          >
            Submit plan
          </button>
        </div>
      )}

      {readyToShip && plan.shipments.length > 0 && (
        <ShipmentsSection plan={plan} busy={busy} runAction={runAction} />
      )}

      <RecentApiCalls plan={plan} />
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Status bar                                                                  //
// --------------------------------------------------------------------------- //

function StatusBar({ plan }: { plan: FBAPlanDetail }) {
  const tone = plan.is_terminal
    ? 'bg-gray-100 border-gray-300 text-gray-700'
    : plan.status === 'error'
      ? 'bg-red-50 border-red-300 text-red-800'
      : plan.is_paused
        ? 'bg-amber-50 border-amber-300 text-amber-900'
        : 'bg-blue-50 border-blue-300 text-blue-900'
  return (
    <div className={`border rounded p-3 mb-4 ${tone}`}>
      <div className="flex items-center justify-between">
        <div>
          <span className="font-mono font-bold">{plan.status}</span>
          {plan.is_paused && (
            <span className="ml-2 text-xs">⏸ waiting for you</span>
          )}
          {plan.current_operation_id && (
            <span className="ml-2 text-xs text-gray-500">
              op: <span className="font-mono">{plan.current_operation_id}</span>
            </span>
          )}
        </div>
        <div className="text-xs text-gray-500">
          {plan.last_polled_at && (
            <span>last poll: {new Date(plan.last_polled_at).toLocaleTimeString()}</span>
          )}
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Error panel + retry                                                          //
// --------------------------------------------------------------------------- //

function ErrorPanel({
  plan,
  busy,
  onRetry,
}: {
  plan: FBAPlanDetail
  busy: boolean
  onRetry: (rewindTo?: import('@/lib/fbaApi').FBAStatus) => void
}) {
  const last = plan.error_log && plan.error_log[plan.error_log.length - 1]
  return (
    <div className="bg-red-50 border border-red-300 rounded p-4 mb-6">
      <h3 className="font-semibold text-red-800 mb-1">
        Workflow stopped on error
      </h3>
      {last && (
        <p className="text-sm text-red-700">
          <span className="font-mono">{last.step}</span>
          {last.exc_type && (
            <span className="text-xs text-red-600"> ({last.exc_type})</span>
          )}
          : {last.message}
        </p>
      )}
      <div className="mt-3">
        <button
          onClick={() => onRetry(undefined)}
          disabled={busy}
          className="bg-amber-600 text-white px-4 py-1.5 rounded text-sm hover:bg-amber-700 disabled:opacity-60"
        >
          Retry from {last ? last.step : 'start'}
        </button>
      </div>
      {plan.error_log && plan.error_log.length > 1 && (
        <details className="mt-2 text-xs text-red-700">
          <summary className="cursor-pointer">
            Full error history ({plan.error_log.length})
          </summary>
          <ul className="list-disc list-inside mt-1">
            {plan.error_log.map((e, i) => (
              <li key={i}>
                <span className="font-mono">{e.step}</span>: {e.message}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Items                                                                       //
// --------------------------------------------------------------------------- //

function ItemsSection({
  plan,
  busy,
  onReload,
  runAction,
}: {
  plan: FBAPlanDetail
  busy: boolean
  onReload: () => void
  runAction: (label: string, fn: () => Promise<unknown>) => Promise<void>
}) {
  const [skus, setSkus] = useState<SKUListRow[]>([])
  const [skuQuery, setSkuQuery] = useState('')
  const [showPicker, setShowPicker] = useState(false)
  const [pickQty, setPickQty] = useState('10')

  // Lazy load SKUs the first time the picker is opened
  useEffect(() => {
    if (!showPicker || skus.length > 0) return
    const qs = new URLSearchParams({ channel: plan.marketplace, page_size: '500' })
    api(`/api/skus/?${qs}`)
      .then((r) => r.json())
      .then((data: { results?: SKUListRow[] } | SKUListRow[]) => {
        const list = Array.isArray(data) ? data : data.results || []
        setSkus(list.filter((s) => s.active))
      })
      .catch(() => {})
  }, [showPicker, skus.length, plan.marketplace])

  const canEdit = plan.status === 'draft'

  const filtered = skuQuery
    ? skus.filter(
        (s) =>
          s.sku.toLowerCase().includes(skuQuery.toLowerCase()) ||
          s.asin.toLowerCase().includes(skuQuery.toLowerCase()),
      )
    : skus.slice(0, 50)

  const addOne = (sku: SKUListRow) => {
    const qty = parseInt(pickQty || '0', 10)
    if (!qty || qty < 1) return
    runAction(`Added ${sku.sku} × ${qty}`, () =>
      addPlanItems(plan.id, [{ sku_id: sku.id, quantity: qty }]),
    ).then(() => {
      setShowPicker(false)
      setSkuQuery('')
      onReload()
    })
  }

  const totalUnits = plan.items.reduce((s, it) => s + it.quantity, 0)

  return (
    <section className="bg-white rounded-lg shadow p-4 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold">
          Items{' '}
          <span className="text-gray-400 font-normal text-sm">
            ({plan.items.length} lines · {totalUnits} units)
          </span>
        </h3>
        {canEdit && (
          <button
            onClick={() => setShowPicker((v) => !v)}
            className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            + Add item
          </button>
        )}
      </div>

      {showPicker && canEdit && (
        <div className="border rounded p-3 mb-3 bg-gray-50">
          <div className="flex items-center gap-2 mb-2">
            <input
              type="text"
              placeholder={`Search ${plan.marketplace} SKUs…`}
              value={skuQuery}
              onChange={(e) => setSkuQuery(e.target.value)}
              className="border rounded px-2 py-1 text-sm flex-1"
              autoFocus
            />
            <label className="text-sm text-gray-600">Qty:</label>
            <input
              type="number"
              min={1}
              value={pickQty}
              onChange={(e) => setPickQty(e.target.value)}
              className="border rounded px-2 py-1 text-sm w-20"
            />
          </div>
          <div className="max-h-60 overflow-y-auto bg-white rounded border">
            {filtered.length === 0 ? (
              <p className="text-gray-400 text-sm p-2">No matches.</p>
            ) : (
              filtered.map((s) => (
                <button
                  key={s.id}
                  onClick={() => addOne(s)}
                  disabled={busy}
                  className="w-full text-left px-3 py-1.5 text-sm hover:bg-blue-50 border-b disabled:opacity-60"
                >
                  <span className="font-mono">{s.sku}</span>
                  {s.asin && (
                    <span className="text-gray-400 ml-2">{s.asin}</span>
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {plan.items.length === 0 ? (
        <p className="text-gray-400 text-sm">No items yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-1.5">M-Number</th>
              <th>SKU</th>
              <th>FNSKU</th>
              <th className="text-right">Qty</th>
              {canEdit && <th className="w-8"></th>}
            </tr>
          </thead>
          <tbody>
            {plan.items.map((item) => (
              <tr key={item.id} className="border-b">
                <td className="py-1.5 font-mono">{item.m_number}</td>
                <td className="font-mono text-gray-700">{item.sku_code}</td>
                <td className="font-mono text-gray-500">
                  {item.fnsku || (
                    <span className="text-red-600">missing</span>
                  )}
                </td>
                <td className="text-right tabular-nums">{item.quantity}</td>
                {canEdit && (
                  <td>
                    <button
                      onClick={() =>
                        runAction(`Removed ${item.sku_code}`, () =>
                          removePlanItem(plan.id, item.id),
                        )
                      }
                      disabled={busy}
                      className="text-red-600 hover:text-red-800 text-xs disabled:opacity-60"
                    >
                      ✕
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

// --------------------------------------------------------------------------- //
// Boxes                                                                       //
// --------------------------------------------------------------------------- //

function BoxesSection({
  plan,
  busy,
  onReload,
  runAction,
}: {
  plan: FBAPlanDetail
  busy: boolean
  onReload: () => void
  runAction: (label: string, fn: () => Promise<unknown>) => Promise<void>
}) {
  const [showForm, setShowForm] = useState(false)
  const [l, setL] = useState('')
  const [w, setW] = useState('')
  const [h, setH] = useState('')
  const [kg, setKg] = useState('')
  const [boxNo, setBoxNo] = useState('')
  const [contents, setContents] = useState<Record<number, number>>({})

  const canEdit =
    plan.status === 'draft' || plan.status === 'packing_options_ready'

  const nextBoxNo = (plan.boxes.reduce((m, b) => Math.max(m, b.box_number), 0) || 0) + 1

  useEffect(() => {
    if (showForm && !boxNo) setBoxNo(String(nextBoxNo))
  }, [showForm, boxNo, nextBoxNo])

  const submit = () => {
    const entries = Object.entries(contents)
      .filter(([, q]) => q > 0)
      .map(([id, q]) => ({ plan_item_id: Number(id), quantity: q }))
    if (entries.length === 0) {
      alert('Box needs at least one item')
      return
    }
    runAction(`Box ${boxNo} added`, () =>
      addBox(plan.id, {
        box_number: Number(boxNo),
        length_cm: l,
        width_cm: w,
        height_cm: h,
        weight_kg: kg,
        contents: entries,
      }),
    ).then(() => {
      setShowForm(false)
      setL('')
      setW('')
      setH('')
      setKg('')
      setBoxNo('')
      setContents({})
      onReload()
    })
  }

  const allocated = new Map<number, number>()
  plan.boxes.forEach((b) =>
    b.contents.forEach((c) => {
      allocated.set(c.plan_item, (allocated.get(c.plan_item) || 0) + c.quantity)
    }),
  )

  return (
    <section className="bg-white rounded-lg shadow p-4 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold">
          Boxes{' '}
          <span className="text-gray-400 font-normal text-sm">
            ({plan.boxes.length})
          </span>
        </h3>
        {canEdit && (
          <button
            onClick={() => setShowForm((v) => !v)}
            className="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            + Add box
          </button>
        )}
      </div>

      {showForm && canEdit && (
        <div className="border rounded p-3 mb-3 bg-gray-50">
          <div className="flex items-end gap-2 flex-wrap mb-2">
            <LabeledNum label="Box #" value={boxNo} onChange={setBoxNo} />
            <LabeledNum label="L (cm)" value={l} onChange={setL} />
            <LabeledNum label="W (cm)" value={w} onChange={setW} />
            <LabeledNum label="H (cm)" value={h} onChange={setH} />
            <LabeledNum label="Wt (kg)" value={kg} onChange={setKg} step="0.01" />
          </div>
          <p className="text-xs text-gray-600 mb-1">Contents:</p>
          <div className="space-y-1 mb-2">
            {plan.items.map((it) => {
              const alreadyInOtherBoxes = allocated.get(it.id) || 0
              const remaining = it.quantity - alreadyInOtherBoxes
              return (
                <div key={it.id} className="flex items-center gap-2 text-sm">
                  <span className="font-mono flex-1">{it.sku_code}</span>
                  <span className="text-xs text-gray-500">
                    {remaining} / {it.quantity} remaining
                  </span>
                  <input
                    type="number"
                    min={0}
                    max={remaining}
                    placeholder="0"
                    value={contents[it.id] ?? ''}
                    onChange={(e) =>
                      setContents((c) => ({
                        ...c,
                        [it.id]: Number(e.target.value) || 0,
                      }))
                    }
                    className="border rounded px-2 py-1 w-20 text-right"
                  />
                </div>
              )
            })}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={submit}
              disabled={busy}
              className="bg-green-600 text-white px-4 py-1.5 rounded text-sm hover:bg-green-700 disabled:opacity-60"
            >
              Save box
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="text-sm text-gray-500"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {plan.boxes.length === 0 ? (
        <p className="text-gray-400 text-sm">No boxes yet.</p>
      ) : (
        <div className="space-y-2">
          {plan.boxes.map((b) => (
            <BoxRow
              key={b.id}
              box={b}
              plan={plan}
              canEdit={canEdit}
              busy={busy}
              runAction={runAction}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function BoxRow({
  box,
  plan,
  canEdit,
  busy,
  runAction,
}: {
  box: FBABox
  plan: FBAPlanDetail
  canEdit: boolean
  busy: boolean
  runAction: (label: string, fn: () => Promise<unknown>) => Promise<void>
}) {
  const planItemsById = new Map(plan.items.map((i) => [i.id, i]))
  const totalUnits = box.contents.reduce((s, c) => s + c.quantity, 0)
  return (
    <div className="border rounded p-2 flex items-start justify-between">
      <div>
        <p className="font-semibold">
          Box #{box.box_number}{' '}
          <span className="text-xs text-gray-500 font-normal">
            {box.length_cm}×{box.width_cm}×{box.height_cm} cm · {box.weight_kg} kg
            {box.amazon_box_id && ` · ${box.amazon_box_id}`}
          </span>
        </p>
        <ul className="text-sm text-gray-700 mt-1">
          {box.contents.map((c) => {
            const it = planItemsById.get(c.plan_item)
            return (
              <li key={c.id}>
                <span className="font-mono">
                  {it?.sku_code || `plan_item #${c.plan_item}`}
                </span>
                <span className="text-gray-400"> × </span>
                <span className="tabular-nums">{c.quantity}</span>
              </li>
            )
          })}
        </ul>
        <p className="text-xs text-gray-400 mt-1">{totalUnits} units total</p>
      </div>
      {canEdit && (
        <button
          onClick={() =>
            runAction(`Box ${box.box_number} removed`, () =>
              deleteBox(plan.id, box.id),
            )
          }
          disabled={busy}
          className="text-red-600 hover:text-red-800 text-sm disabled:opacity-60"
        >
          ✕
        </button>
      )}
    </div>
  )
}

function LabeledNum({
  label,
  value,
  onChange,
  step,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  step?: string
}) {
  return (
    <div>
      <label className="block text-xs text-gray-500">{label}</label>
      <input
        type="number"
        min={0}
        step={step || '0.1'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border rounded px-2 py-1 w-20 text-sm"
      />
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Packing / placement option pickers                                           //
// --------------------------------------------------------------------------- //

function PackingOptionsPicker({
  plan,
  busy,
  onPick,
}: {
  plan: FBAPlanDetail
  busy: boolean
  onPick: (id: string) => void
}) {
  const options = plan.packing_options_snapshot?.packingOptions || []
  return (
    <section className="bg-amber-50 border border-amber-300 rounded p-4 mb-6">
      <h3 className="font-semibold text-amber-900 mb-2">
        Pick a packing option
      </h3>
      <p className="text-xs text-amber-800 mb-3">
        Amazon returned {options.length} option{options.length === 1 ? '' : 's'}.
        Pick one to continue the workflow.
      </p>
      <div className="space-y-2">
        {options.map((o) => (
          <div
            key={o.packingOptionId}
            className="bg-white border rounded p-3 flex items-center justify-between"
          >
            <div>
              <p className="font-mono text-sm">{o.packingOptionId}</p>
              {o.fees && o.fees.length > 0 && (
                <p className="text-xs text-gray-500">
                  Fees:{' '}
                  {o.fees
                    .map(
                      (f) =>
                        `${f.value?.amount ?? '?'} ${f.value?.code ?? ''}`,
                    )
                    .join(', ')}
                </p>
              )}
              {o.expiration && (
                <p className="text-xs text-gray-400">
                  expires {new Date(o.expiration).toLocaleString()}
                </p>
              )}
            </div>
            <button
              onClick={() => onPick(o.packingOptionId)}
              disabled={busy}
              className="bg-amber-600 text-white px-4 py-1.5 rounded text-sm hover:bg-amber-700 disabled:opacity-60"
            >
              Pick
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}

function PlacementOptionsPicker({
  plan,
  busy,
  onPick,
}: {
  plan: FBAPlanDetail
  busy: boolean
  onPick: (id: string) => void
}) {
  const options = plan.placement_options_snapshot?.placementOptions || []
  return (
    <section className="bg-amber-50 border border-amber-300 rounded p-4 mb-6">
      <h3 className="font-semibold text-amber-900 mb-2">
        Pick a placement option
      </h3>
      <p className="text-xs text-amber-800 mb-3">
        Amazon returned {options.length} placement option
        {options.length === 1 ? '' : 's'}.
      </p>
      <div className="space-y-2">
        {options.map((o) => (
          <div
            key={o.placementOptionId}
            className="bg-white border rounded p-3 flex items-center justify-between"
          >
            <div>
              <p className="font-mono text-sm">{o.placementOptionId}</p>
              {o.shipmentIds && (
                <p className="text-xs text-gray-500">
                  {o.shipmentIds.length} shipment
                  {o.shipmentIds.length === 1 ? '' : 's'}
                </p>
              )}
              {o.fees && o.fees.length > 0 && (
                <p className="text-xs text-gray-500">
                  Fees:{' '}
                  {o.fees
                    .map(
                      (f) =>
                        `${f.value?.amount ?? '?'} ${f.value?.code ?? ''}`,
                    )
                    .join(', ')}
                </p>
              )}
            </div>
            <button
              onClick={() => onPick(o.placementOptionId)}
              disabled={busy}
              className="bg-amber-600 text-white px-4 py-1.5 rounded text-sm hover:bg-amber-700 disabled:opacity-60"
            >
              Pick
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}

// --------------------------------------------------------------------------- //
// Shipments + manual dispatch                                                  //
// --------------------------------------------------------------------------- //

function ShipmentsSection({
  plan,
  busy,
  runAction,
}: {
  plan: FBAPlanDetail
  busy: boolean
  runAction: (label: string, fn: () => Promise<unknown>) => Promise<void>
}) {
  return (
    <section className="bg-white rounded-lg shadow p-4 mb-6">
      <h3 className="font-semibold mb-3">
        Shipments ({plan.shipments.length})
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        Labels are fetched automatically. Ben books the carrier externally
        (Phase 2 scope — automation deferred) and records the tracking number
        below.
      </p>
      <div className="space-y-3">
        {plan.shipments.map((s) => (
          <ShipmentRow key={s.id} shipment={s} plan={plan} busy={busy} runAction={runAction} />
        ))}
      </div>
    </section>
  )
}

function ShipmentRow({
  shipment,
  plan,
  busy,
  runAction,
}: {
  shipment: FBAShipment
  plan: FBAPlanDetail
  busy: boolean
  runAction: (label: string, fn: () => Promise<unknown>) => Promise<void>
}) {
  const [carrier, setCarrier] = useState(shipment.carrier_name)
  const [tracking, setTracking] = useState(shipment.tracking_number)
  const dispatched = !!shipment.dispatched_at

  const downloadPdf = async () => {
    try {
      const blob = await downloadLabels(plan.id, shipment.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${shipment.shipment_confirmation_id || shipment.shipment_id}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Labels download failed')
    }
  }

  return (
    <div className="border rounded p-3">
      <div className="flex items-center justify-between mb-2">
        <div>
          <p className="font-semibold">
            {shipment.shipment_confirmation_id || shipment.shipment_id}
          </p>
          <p className="text-xs text-gray-500">
            → {shipment.destination_fc || 'unknown FC'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {dispatched && (
            <span className="bg-green-100 text-green-800 text-xs px-2 py-0.5 rounded">
              dispatched {new Date(shipment.dispatched_at!).toLocaleDateString()}
            </span>
          )}
          {shipment.labels_url && (
            <button
              onClick={downloadPdf}
              className="text-sm px-3 py-1 border border-blue-300 text-blue-700 rounded hover:bg-blue-50"
            >
              Labels PDF
            </button>
          )}
        </div>
      </div>
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label className="block text-xs text-gray-500">Carrier</label>
          <input
            type="text"
            value={carrier}
            onChange={(e) => setCarrier(e.target.value)}
            placeholder="Evri, UPS, DHL…"
            disabled={dispatched}
            className="border rounded px-2 py-1 text-sm w-full"
          />
        </div>
        <div className="flex-1">
          <label className="block text-xs text-gray-500">Tracking number</label>
          <input
            type="text"
            value={tracking}
            onChange={(e) => setTracking(e.target.value)}
            disabled={dispatched}
            className="border rounded px-2 py-1 text-sm w-full"
          />
        </div>
        {!dispatched && (
          <button
            onClick={() =>
              runAction('Tracking captured', () =>
                dispatchShipment(plan.id, shipment.id, {
                  carrier_name: carrier,
                  tracking_number: tracking,
                }),
              )
            }
            disabled={busy || !carrier || !tracking}
            className="bg-green-600 text-white px-4 py-1.5 rounded text-sm hover:bg-green-700 disabled:opacity-60"
          >
            Mark dispatched
          </button>
        )}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Recent API calls                                                            //
// --------------------------------------------------------------------------- //

function RecentApiCalls({ plan }: { plan: FBAPlanDetail }) {
  if (plan.recent_api_calls.length === 0) return null
  return (
    <section className="bg-white rounded-lg shadow p-4 mb-6">
      <details>
        <summary className="font-semibold cursor-pointer">
          Recent API calls ({plan.recent_api_calls.length})
        </summary>
        <table className="w-full text-xs mt-3">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-1">When</th>
              <th>Operation</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {plan.recent_api_calls.map((c) => (
              <tr key={c.id} className="border-b">
                <td className="py-1 text-gray-500">
                  {new Date(c.created_at).toLocaleTimeString()}
                </td>
                <td className="font-mono">{c.operation_name}</td>
                <td
                  className={
                    c.response_status >= 400 ? 'text-red-600' : 'text-green-600'
                  }
                >
                  {c.response_status}
                </td>
                <td className="text-gray-500">{c.duration_ms} ms</td>
                <td className="text-red-600 truncate max-w-[300px]">
                  {c.error_message}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}

