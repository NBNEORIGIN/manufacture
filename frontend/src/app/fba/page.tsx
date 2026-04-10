'use client'

/**
 * FBA Shipment Automation — plans list page.
 *
 * Lists all FBAShipmentPlans (the automated v2024-03-20 flow). The
 * legacy manual /shipments module remains for non-Amazon exports.
 *
 * Shows a preflight widget for the selected marketplace so Ben can see
 * at a glance whether SKUs are missing FNSKUs or dimensions before
 * starting a new plan.
 */

import { useCallback, useEffect, useState } from 'react'
import {
  FBAPlanListItem,
  FBAStatus,
  FBAApiError,
  PreflightResult,
  createFbaPlan,
  listFbaPlans,
  preflight,
} from '@/lib/fbaApi'

const MARKETPLACES = ['UK', 'US', 'CA', 'AU', 'DE'] as const

const STATUS_COLOURS: Partial<Record<FBAStatus, string>> = {
  draft: 'bg-gray-100 text-gray-700',
  items_added: 'bg-gray-200 text-gray-800',
  plan_creating: 'bg-blue-100 text-blue-800',
  plan_created: 'bg-blue-100 text-blue-800',
  packing_options_generating: 'bg-blue-100 text-blue-800',
  packing_options_ready: 'bg-amber-100 text-amber-900',
  packing_info_setting: 'bg-blue-100 text-blue-800',
  packing_info_set: 'bg-blue-100 text-blue-800',
  packing_option_confirming: 'bg-blue-100 text-blue-800',
  packing_option_confirmed: 'bg-blue-100 text-blue-800',
  placement_options_generating: 'bg-blue-100 text-blue-800',
  placement_options_ready: 'bg-amber-100 text-amber-900',
  placement_option_confirming: 'bg-blue-100 text-blue-800',
  placement_option_confirmed: 'bg-blue-100 text-blue-800',
  transport_options_generating: 'bg-blue-100 text-blue-800',
  transport_options_ready: 'bg-blue-100 text-blue-800',
  delivery_window_generating: 'bg-blue-100 text-blue-800',
  delivery_window_ready: 'bg-blue-100 text-blue-800',
  transport_confirming: 'bg-blue-100 text-blue-800',
  transport_confirmed: 'bg-blue-100 text-blue-800',
  labels_ready: 'bg-amber-100 text-amber-900',
  ready_to_ship: 'bg-purple-100 text-purple-900',
  dispatched: 'bg-green-100 text-green-800',
  delivered: 'bg-green-200 text-green-900',
  error: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-200 text-gray-500 line-through',
}

export default function FbaPlansPage() {
  const [plans, setPlans] = useState<FBAPlanListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const [marketplaceFilter, setMarketplaceFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const [showForm, setShowForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newMarketplace, setNewMarketplace] = useState<string>('UK')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const [preflightFor, setPreflightFor] = useState<string>('UK')
  const [preflightData, setPreflightData] = useState<PreflightResult | null>(null)
  const [preflightError, setPreflightError] = useState('')

  const loadPlans = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await listFbaPlans({
        marketplace: marketplaceFilter || undefined,
        status: statusFilter || undefined,
      })
      setPlans(data.results)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load plans')
    } finally {
      setLoading(false)
    }
  }, [marketplaceFilter, statusFilter])

  useEffect(() => {
    loadPlans()
  }, [loadPlans])

  // Preflight lookup — runs whenever preflightFor changes
  useEffect(() => {
    let cancelled = false
    setPreflightError('')
    setPreflightData(null)
    preflight(preflightFor)
      .then((d) => {
        if (!cancelled) setPreflightData(d)
      })
      .catch((e) => {
        if (!cancelled) {
          setPreflightError(e instanceof Error ? e.message : 'Preflight failed')
        }
      })
    return () => {
      cancelled = true
    }
  }, [preflightFor])

  const handleCreate = async () => {
    if (!newName.trim()) {
      setCreateError('Name is required')
      return
    }
    setCreating(true)
    setCreateError('')
    try {
      const plan = await createFbaPlan({
        name: newName.trim(),
        marketplace: newMarketplace,
      })
      setMessage(`Created plan #${plan.id}`)
      setTimeout(() => setMessage(''), 3000)
      setNewName('')
      setShowForm(false)
      await loadPlans()
      // Navigate straight into the new plan
      window.location.href = `/fba/${plan.id}`
    } catch (e) {
      if (e instanceof FBAApiError) {
        setCreateError(e.message)
      } else {
        setCreateError(e instanceof Error ? e.message : 'Create failed')
      }
    } finally {
      setCreating(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold">FBA Automation</h2>
          <button
            onClick={() => {
              setShowForm((v) => !v)
              setCreateError('')
            }}
            className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700"
          >
            New Plan
          </button>
          {message && (
            <span className="text-green-600 text-sm font-medium">{message}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={marketplaceFilter}
            onChange={(e) => setMarketplaceFilter(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          >
            <option value="">All marketplaces</option>
            {MARKETPLACES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          >
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="packing_options_ready">Pick packing option</option>
            <option value="placement_options_ready">Pick placement option</option>
            <option value="labels_ready">Labels ready</option>
            <option value="ready_to_ship">Ready to ship</option>
            <option value="dispatched">Dispatched</option>
            <option value="error">Error</option>
            <option value="cancelled">Cancelled</option>
            <option value="delivered">Delivered</option>
          </select>
        </div>
      </div>

      {showForm && (
        <div className="bg-white rounded-lg shadow p-4 mb-6">
          <div className="flex items-center gap-4">
            <input
              type="text"
              placeholder="Plan name (e.g. 'UK restock 2026-04')"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="border rounded px-3 py-2 flex-1 max-w-md"
            />
            <select
              value={newMarketplace}
              onChange={(e) => setNewMarketplace(e.target.value)}
              className="border rounded px-3 py-2"
            >
              {MARKETPLACES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="bg-green-600 text-white px-4 py-2 rounded text-sm hover:bg-green-700 disabled:opacity-60"
            >
              {creating ? 'Creating…' : 'Create'}
            </button>
            <button
              onClick={() => {
                setShowForm(false)
                setCreateError('')
              }}
              className="text-gray-500 text-sm"
            >
              Cancel
            </button>
          </div>
          {createError && (
            <p className="mt-2 text-sm text-red-600">{createError}</p>
          )}
        </div>
      )}

      {/* Preflight widget */}
      <div className="bg-white rounded-lg shadow p-4 mb-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-gray-700">
            Readiness preflight
          </h3>
          <select
            value={preflightFor}
            onChange={(e) => setPreflightFor(e.target.value)}
            className="border rounded px-2 py-1 text-xs"
          >
            {MARKETPLACES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        {preflightError && (
          <p className="text-sm text-red-600">{preflightError}</p>
        )}
        {preflightData && (
          <div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
              <Stat label="Active SKUs" value={preflightData.active_skus} />
              <Stat
                label="With FNSKU"
                value={`${preflightData.with_fnsku} / ${preflightData.active_skus}`}
                ok={preflightData.with_fnsku === preflightData.active_skus}
              />
              <Stat
                label="With dims"
                value={`${preflightData.with_dims} / ${preflightData.active_skus}`}
                ok={preflightData.with_dims === preflightData.active_skus}
              />
              <Stat label="Fully ready" value={preflightData.fully_ready} />
              <div className="flex items-center">
                {preflightData.ready ? (
                  <span className="inline-block bg-green-100 text-green-800 px-3 py-1 rounded-full text-xs font-semibold">
                    ready
                  </span>
                ) : (
                  <span className="inline-block bg-amber-100 text-amber-900 px-3 py-1 rounded-full text-xs font-semibold">
                    not ready
                  </span>
                )}
              </div>
            </div>
            {(preflightData.missing_fnsku.length > 0 ||
              preflightData.missing_dims.length > 0) && (
              <details className="mt-3 text-xs text-gray-700">
                <summary className="cursor-pointer hover:text-blue-600">
                  {preflightData.missing_fnsku.length} missing FNSKU,{' '}
                  {preflightData.missing_dims.length} missing dims
                </summary>
                <div className="grid grid-cols-2 gap-4 mt-2">
                  <div>
                    <p className="font-semibold text-gray-600 mb-1">
                      Missing FNSKU
                    </p>
                    <ul className="list-disc list-inside text-gray-500 max-h-40 overflow-y-auto">
                      {preflightData.missing_fnsku.slice(0, 50).map((s) => (
                        <li key={`${s.m_number}-${s.sku}`}>
                          <span className="font-mono">{s.m_number}</span> — {s.sku}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="font-semibold text-gray-600 mb-1">
                      Missing shipping dims
                    </p>
                    <ul className="list-disc list-inside text-gray-500 max-h-40 overflow-y-auto">
                      {preflightData.missing_dims.slice(0, 50).map((p) => (
                        <li key={p.m_number}>
                          <span className="font-mono">{p.m_number}</span> —{' '}
                          {p.description}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </details>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 mb-4 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-gray-400">Loading…</p>
      ) : plans.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          No plans yet. Click <strong>New Plan</strong> to get started.
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b text-left">
                <th className="px-4 py-2 w-12">#</th>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Marketplace</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2 text-right">Items</th>
                <th className="px-4 py-2 text-right">Boxes</th>
                <th className="px-4 py-2 text-right">Ships</th>
                <th className="px-4 py-2">Inbound plan</th>
                <th className="px-4 py-2">Updated</th>
              </tr>
            </thead>
            <tbody>
              {plans.map((p) => (
                <tr
                  key={p.id}
                  onClick={() => (window.location.href = `/fba/${p.id}`)}
                  className="border-b cursor-pointer hover:bg-gray-50"
                >
                  <td className="px-4 py-2 font-mono text-gray-400">{p.id}</td>
                  <td className="px-4 py-2 font-medium">{p.name}</td>
                  <td className="px-4 py-2">{p.marketplace}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        STATUS_COLOURS[p.status] || 'bg-gray-100'
                      }`}
                    >
                      {p.status}
                    </span>
                    {p.is_paused && (
                      <span className="ml-1 text-xs text-amber-700">⏸</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {p.item_count}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {p.box_count}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {p.shipment_count}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-500 truncate max-w-[160px]">
                    {p.inbound_plan_id || '—'}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {new Date(p.updated_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Stat({
  label,
  value,
  ok,
}: {
  label: string
  value: number | string
  ok?: boolean
}) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p
        className={`text-lg font-bold ${
          ok === undefined ? '' : ok ? 'text-green-600' : 'text-amber-700'
        }`}
      >
        {value}
      </p>
    </div>
  )
}
