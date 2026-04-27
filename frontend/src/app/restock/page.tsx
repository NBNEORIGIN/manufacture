'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '@/lib/api'
import HelpButton from '@/components/HelpButton'

const MARKETPLACES = ['GB', 'US', 'CA', 'AU', 'DE', 'FR']

interface Exclusion {
  m_number: string
  reason: string
  added_by: string
  created_at: string
}

interface RestockItem {
  id: number
  merchant_sku: string
  asin: string
  m_number: string
  product_name: string
  units_available: number
  units_inbound: number
  units_reserved: number
  units_unfulfillable: number
  units_total: number
  days_of_supply_amazon: number | null
  units_sold_7d: number
  units_sold_30d: number
  units_sold_60d: number
  units_sold_90d: number
  alert: string
  amazon_recommended_qty: number | null
  newsvendor_qty: number | null
  newsvendor_confidence: number | null
  newsvendor_notes: string
  approved_qty: number | null
  production_order_id: number | null
}

interface PlanSummary {
  total_items: number
  action_items: number
  newsvendor_total_units: number
  filtered_count: number
}

interface SyncStatus {
  status: string
  row_count: number
  error_message: string
  created_at: string
}

function ConfidenceDot({ confidence }: { confidence: number | null }) {
  // Small coloured circle — no emoji. Bordered slate for null, filled for values.
  if (confidence === null) {
    return (
      <span
        className="inline-block w-2.5 h-2.5 rounded-full border border-slate-300 align-middle"
        title="Confidence unknown"
      />
    )
  }
  const pct = (confidence * 100).toFixed(0)
  let bg = 'bg-rose-500'
  if (confidence >= 0.8) bg = 'bg-emerald-500'
  else if (confidence >= 0.5) bg = 'bg-amber-400'
  return (
    <span
      className={`inline-block w-2.5 h-2.5 rounded-full align-middle ${bg}`}
      title={`Confidence: ${pct}%`}
    />
  )
}

function AlertBadge({ alert }: { alert: string }) {
  if (!alert) return null
  const styles: Record<string, string> = {
    out_of_stock: 'bg-red-100 text-red-800',
    reorder_now: 'bg-orange-100 text-orange-800',
  }
  const label: Record<string, string> = {
    out_of_stock: 'OUT OF STOCK',
    reorder_now: 'REORDER',
  }
  const cls = styles[alert] || 'bg-gray-100 text-gray-600'
  return (
    <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${cls}`}>
      {label[alert] || alert}
    </span>
  )
}

function SortHeader({ col, label, sortCol, sortDir, onSort, className = '' }: {
  col: string; label: string; sortCol: string; sortDir: 'asc' | 'desc'
  onSort: (col: string) => void; className?: string
}) {
  const active = sortCol === col
  return (
    <th
      className={`px-3 py-2 font-semibold cursor-pointer select-none hover:bg-gray-100 ${className}`}
      onClick={() => onSort(col)}
    >
      {label} {active ? (sortDir === 'asc' ? '▲' : '▼') : <span className="text-gray-300">↕</span>}
    </th>
  )
}

type DemandMetric = '30d×3' | 'actual_90d' | '60d×1.5' | '7d×13'

const DEMAND_METRICS: { key: DemandMetric; label: string; description: string }[] = [
  { key: '30d×3', label: '30d × 3', description: '30-day sales extrapolated to 90 days' },
  { key: 'actual_90d', label: 'Actual 90d', description: "Amazon's actual 90-day units shipped" },
  { key: '60d×1.5', label: '60d × 1.5', description: '60-day sales extrapolated to 90 days' },
  { key: '7d×13', label: '7d × 13', description: 'Weekly run-rate projected to 90 days' },
]

function calcDemand(item: RestockItem, metric: DemandMetric): number {
  switch (metric) {
    case '30d×3': return item.units_sold_30d * 3
    case 'actual_90d': return item.units_sold_90d
    case '60d×1.5': return Math.ceil(item.units_sold_60d * 1.5)
    case '7d×13': return item.units_sold_7d * 13
  }
}

function calcRecommended(item: RestockItem, metric: DemandMetric): number {
  return Math.max(0, calcDemand(item, metric) - item.units_total)
}

function salesForMetric(item: RestockItem, metric: DemandMetric): number {
  switch (metric) {
    case '30d×3': return item.units_sold_30d
    case 'actual_90d': return item.units_sold_90d
    case '60d×1.5': return item.units_sold_60d
    case '7d×13': return item.units_sold_7d
  }
}

function salesColumnLabel(metric: DemandMetric): string {
  switch (metric) {
    case '30d×3': return '30d Sales'
    case 'actual_90d': return '90d Sales'
    case '60d×1.5': return '60d Sales'
    case '7d×13': return '7d Sales'
  }
}

function salesSortKey(metric: DemandMetric): string {
  switch (metric) {
    case '30d×3': return 'units_sold_30d'
    case 'actual_90d': return 'units_sold_90d'
    case '60d×1.5': return 'units_sold_60d'
    case '7d×13': return 'units_sold_7d'
  }
}

export default function RestockPage() {
  const [activeMarketplace, setActiveMarketplace] = useState('GB')
  const [items, setItems] = useState<RestockItem[]>([])
  const [summary, setSummary] = useState<PlanSummary | null>(null)
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [alertFilter, setAlertFilter] = useState('all')
  const [dosFilter, setDosFilter] = useState<string>('all')
  const [metric, setMetric] = useState<DemandMetric>('30d×3')
  const [search, setSearch] = useState('')
  const [editQtys, setEditQtys] = useState<Record<number, number>>({})
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [statusMsg, setStatusMsg] = useState('')
  const [approving, setApproving] = useState(false)
  const [creatingPO, setCreatingPO] = useState(false)
  const [exclusions, setExclusions] = useState<Exclusion[]>([])
  const [newExclusion, setNewExclusion] = useState('')
  const [newExclusionReason, setNewExclusionReason] = useState('')
  const [showExclusions, setShowExclusions] = useState(false)
  const [sortCol, setSortCol] = useState<string>('alert')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadExclusions = useCallback(async () => {
    try {
      const res = await api('/api/restock/exclusions/')
      const data = await res.json()
      setExclusions(data.exclusions || [])
    } catch { /* silent */ }
  }, [])

  const handleAddExclusion = async () => {
    const m = newExclusion.trim().toUpperCase()
    if (!m) return
    try {
      await api('/api/restock/exclusions/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ m_number: m, reason: newExclusionReason }),
      })
      setNewExclusion('')
      setNewExclusionReason('')
      loadExclusions()
    } catch { /* silent */ }
  }

  const handleAddExclusion_inline = async (m_number: string) => {
    try {
      await api('/api/restock/exclusions/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ m_number, reason: 'Personalised — marked from restock planner' }),
      })
      loadExclusions()
    } catch { /* silent */ }
  }

  const handleRemoveExclusion = async (m_number: string) => {
    try {
      await api('/api/restock/exclusions/', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ m_number }),
      })
      loadExclusions()
    } catch { /* silent */ }
  }

  const loadPlan = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (alertFilter === 'action') params.set('alert', 'action')
      if (search) params.set('search', search)
      const res = await api(`/api/restock/${activeMarketplace}/?${params}`)
      const data = await res.json()
      setItems(data.items || [])
      setSummary(data.summary || null)
      // Pre-fill editQtys from approved_qty or metric-based calculation
      const qtys: Record<number, number> = {}
      for (const item of data.items || []) {
        qtys[item.id] = item.approved_qty ?? calcRecommended(item, metric)
      }
      setEditQtys(qtys)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [activeMarketplace, alertFilter, search])

  const checkSyncStatus = useCallback(async () => {
    try {
    const res = await api(`/api/restock/${activeMarketplace}/status/`)
    const data = await res.json()
    setSyncStatus(data)
    if (data.status === 'complete') {
      setSyncing(false)
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
      loadPlan()
    } else if (data.status === 'error') {
      setSyncing(false)
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
      setStatusMsg(`Sync error: ${data.error_message}`)
    }
    } catch { /* silent — no sync yet */ }
  }, [activeMarketplace, loadPlan])

  useEffect(() => {
    loadPlan()
    checkSyncStatus()
    loadExclusions()
  }, [activeMarketplace])

  // Recalculate send qtys when metric changes (only for non-approved items)
  useEffect(() => {
    if (items.length === 0) return
    setEditQtys(prev => {
      const next = { ...prev }
      for (const item of items) {
        if (item.approved_qty == null) {
          next[item.id] = calcRecommended(item, metric)
        }
      }
      return next
    })
  }, [metric, items])

  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = null
  }, [activeMarketplace])

  const handleSync = async () => {
    setSyncing(true)
    setStatusMsg('')
    try {
      await api(`/api/restock/${activeMarketplace}/sync/`, { method: 'POST' })
      pollRef.current = setInterval(checkSyncStatus, 10000)
      checkSyncStatus()
    } catch {
      setSyncing(false)
      setStatusMsg('Failed to start sync')
    }
  }

  const handleSort = (col: string) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('desc') }
  }

  // Derived: exclusion set for O(1) lookups
  const excludedSet = new Set(exclusions.map(e => e.m_number))

  // Derived: filtered items (DoS filter applied client-side)
  const filteredItems = items.filter(item => {
    const dos = item.days_of_supply_amazon
    if (dosFilter === 'critical') return dos !== null && dos < 14
    if (dosFilter === 'low') return dos !== null && dos < 30
    if (dosFilter === 'ok') return dos !== null && dos >= 30 && dos <= 90
    if (dosFilter === 'overstocked') return dos === null || dos > 90
    return true
  })

  // Derived: sorted items
  const sortedItems = [...filteredItems].sort((a, b) => {
    const mul = sortDir === 'asc' ? 1 : -1
    if (sortCol === 'rec_qty') {
      return mul * (calcRecommended(a, metric) - calcRecommended(b, metric))
    }
    const av = (a as any)[sortCol] ?? 0
    const bv = (b as any)[sortCol] ?? 0
    if (typeof av === 'string') return mul * av.localeCompare(bv)
    return mul * (av - bv)
  })

  const toggleSelect = (id: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selected.size === filteredItems.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(filteredItems.map(i => i.id)))
    }
  }

  const handleApprove = async () => {
    if (selected.size === 0) return
    setApproving(true)
    const payload = Array.from(selected).map(id => ({
      id,
      approved_qty: editQtys[id] ?? 0,
    }))
    try {
      await api('/api/restock/approve/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: payload }),
      })
      setStatusMsg(`Approved ${selected.size} items`)
      setSelected(new Set())
      loadPlan()
    } catch {
      setStatusMsg('Approval failed')
    } finally {
      setApproving(false)
      setTimeout(() => setStatusMsg(''), 4000)
    }
  }

  const handleCreateProduction = async () => {
    setCreatingPO(true)
    try {
      const res = await api('/api/restock/create-production/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ marketplace: activeMarketplace }),
      })
      const data = await res.json()
      setStatusMsg(data.message || `Created ${data.created} production orders`)
      loadPlan()
    } catch {
      setStatusMsg('Failed to create production orders')
    } finally {
      setCreatingPO(false)
      setTimeout(() => setStatusMsg(''), 5000)
    }
  }

  const selectedItems = items.filter(i => selected.has(i.id))
  const totalSelectedUnits = selectedItems.reduce((sum, i) => sum + (editQtys[i.id] ?? 0), 0)

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-bold">FBA Restock Planner</h2>
          <HelpButton tabKey="restock" />
          {statusMsg && (
            <span className="text-sm font-medium text-green-700 bg-green-50 px-2 py-1 rounded">
              {statusMsg}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {syncing && (
            <span className="text-sm text-blue-600 animate-pulse">
              Syncing… (5-15 min) — polling every 10s
            </span>
          )}
          <button
            onClick={handleSync}
            disabled={syncing}
            className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {syncing ? 'Syncing…' : `↓ Sync ${activeMarketplace}`}
          </button>
        </div>
      </div>

      {/* Marketplace tabs */}
      <div className="flex gap-1 mb-4">
        {MARKETPLACES.map(mp => (
          <button
            key={mp}
            onClick={() => setActiveMarketplace(mp)}
            className={`px-3 py-1 rounded text-sm font-medium ${
              activeMarketplace === mp
                ? 'bg-blue-600 text-white'
                : 'bg-white border border-gray-200 hover:bg-gray-50'
            }`}
          >
            {mp}
          </button>
        ))}
      </div>

      {/* Summary bar */}
      {summary && (
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-2 mb-4 flex items-center gap-6 text-sm text-gray-600">
          {syncStatus?.created_at && (
            <span>
              Last synced:{' '}
              <span className="font-medium">
                {new Date(syncStatus.created_at).toLocaleString('en-GB')}
              </span>
            </span>
          )}
          <span>
            <span className="font-semibold text-gray-900">{summary.total_items ?? 0}</span> items
          </span>
          <span>
            <span className="font-semibold text-red-600">{summary.action_items ?? 0}</span> need action
          </span>
          <span>
            Restock total ({DEMAND_METRICS.find(m => m.key === metric)?.label}):{' '}
            <span className="font-semibold text-gray-900">
              {items.reduce((sum, i) => sum + calcRecommended(i, metric), 0).toLocaleString()} units
            </span>
          </span>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 mb-3">
        <select
          value={alertFilter}
          onChange={e => setAlertFilter(e.target.value)}
          className="border border-gray-200 rounded px-2 py-1.5 text-sm"
        >
          <option value="all">All items</option>
          <option value="action">Needs action only</option>
        </select>
        <select
          value={dosFilter}
          onChange={e => setDosFilter(e.target.value)}
          className="border border-gray-200 rounded px-2 py-1.5 text-sm"
        >
          <option value="all">All DoS</option>
          <option value="critical">Critical (&lt;14d)</option>
          <option value="low">Low (&lt;30d)</option>
          <option value="ok">OK (30–90d)</option>
          <option value="overstocked">Overstocked (&gt;90d)</option>
        </select>
        <select
          value={metric}
          onChange={e => setMetric(e.target.value as DemandMetric)}
          className="border border-gray-200 rounded px-2 py-1.5 text-sm"
          title="Demand metric used for restock quantity calculation"
        >
          {DEMAND_METRICS.map(m => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Search SKU / M-number…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && loadPlan()}
          className="border border-gray-200 rounded px-2 py-1.5 text-sm w-64"
        />
        <button
          onClick={loadPlan}
          className="text-sm text-blue-600 hover:underline"
        >
          Search
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : items.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          {syncStatus?.status === 'running' ? (
            'SP-API report is being generated. This takes 5–15 minutes.'
          ) : (
            <>No restock data for {activeMarketplace}. Click Sync to download from Amazon.</>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm grid-cells">
            <thead>
              <tr className="bg-gray-50 border-b text-left">
                <th className="px-3 py-2 w-8">
                  <input
                    type="checkbox"
                    checked={selected.size === filteredItems.length && filteredItems.length > 0}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th className="px-2 py-2 font-semibold text-center w-8" title="Personalised (D2C only)">P</th>
                <SortHeader col="m_number" label="M-number" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                <th className="px-3 py-2 font-semibold">SKU</th>
                <SortHeader col="alert" label="Alert" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                <SortHeader col="units_total" label="FBA Total" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <SortHeader col={salesSortKey(metric)} label={salesColumnLabel(metric)} sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <SortHeader col="days_of_supply_amazon" label="DoS" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <SortHeader col="amazon_recommended_qty" label="Amazon Rec." sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <SortHeader col="rec_qty" label="Rec. Qty" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} className="text-right" />
                <th className="px-3 py-2 font-semibold text-right w-28">Send qty</th>
              </tr>
            </thead>
            <tbody>
              {sortedItems.map(item => (
                <tr
                  key={item.id}
                  className={`border-b cursor-pointer hover:bg-gray-50 ${
                    selected.has(item.id) ? 'bg-blue-50' : ''
                  } ${item.alert === 'out_of_stock' ? 'border-l-2 border-l-red-400' : ''} ${
                    excludedSet.has(item.m_number) ? 'opacity-50' : ''
                  }`}
                  onClick={() => toggleSelect(item.id)}
                >
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={selected.has(item.id)}
                      onChange={() => toggleSelect(item.id)}
                      onClick={e => e.stopPropagation()}
                    />
                  </td>
                  <td className="px-2 py-2 text-center">
                    {item.m_number ? (
                      <input
                        type="checkbox"
                        title={excludedSet.has(item.m_number) ? 'Personalised — click to restore to FBA' : 'Mark as personalised (D2C only)'}
                        checked={excludedSet.has(item.m_number)}
                        onChange={e => {
                          e.stopPropagation()
                          if (e.target.checked) handleAddExclusion_inline(item.m_number)
                          else handleRemoveExclusion(item.m_number)
                        }}
                        onClick={e => e.stopPropagation()}
                        className="cursor-pointer accent-purple-600"
                      />
                    ) : null}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {item.m_number || (
                      <span className="text-gray-400 italic">unresolved</span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs max-w-[160px] truncate" title={item.merchant_sku}>
                    {item.merchant_sku}
                  </td>
                  <td className="px-3 py-2">
                    <AlertBadge alert={item.alert} />
                  </td>
                  <td
                    className="px-3 py-2 text-right cursor-help"
                    title={`Available: ${item.units_available}\nInbound: ${item.units_inbound}\nReserved: ${item.units_reserved}\nUnfulfillable: ${item.units_unfulfillable}\nTotal: ${item.units_total}`}
                  >
                    {item.units_total}
                    {(item.units_inbound > 0 || item.units_reserved > 0) && (
                      <span className="text-gray-400 text-xs ml-1">
                        ({item.units_available}
                        {item.units_inbound > 0 && <span className="text-blue-400">+{item.units_inbound}</span>}
                        {item.units_reserved > 0 && <span className="text-amber-400">+{item.units_reserved}</span>}
                        )
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">{salesForMetric(item, metric)}</td>
                  <td className="px-3 py-2 text-right text-gray-500">
                    {item.days_of_supply_amazon !== null
                      ? `${item.days_of_supply_amazon}d`
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-600">
                    {item.amazon_recommended_qty ?? '—'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {(() => {
                      const rec = calcRecommended(item, metric)
                      const demand = calcDemand(item, metric)
                      const note = `${demand} demand − ${item.units_total} FBA total = ${rec}`
                      return (
                        <span title={note} className="cursor-help">
                          {rec}{' '}
                          <ConfidenceDot confidence={item.newsvendor_confidence} />
                        </span>
                      )
                    })()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {item.production_order_id ? (
                      <span className="text-xs text-green-700 bg-green-100 px-1.5 py-0.5 rounded">
                        PO-{item.production_order_id}
                      </span>
                    ) : (
                      <input
                        type="number"
                        min={0}
                        value={editQtys[item.id] ?? 0}
                        onChange={e => {
                          e.stopPropagation()
                          setEditQtys(prev => ({ ...prev, [item.id]: parseInt(e.target.value) || 0 }))
                        }}
                        onClick={e => e.stopPropagation()}
                        className="w-20 border border-gray-300 rounded px-1.5 py-1 text-right text-sm"
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* D2C Exclusions panel */}
      <div className="mt-6">
        <button
          onClick={() => setShowExclusions(v => !v)}
          className="text-sm text-gray-500 hover:text-gray-800 flex items-center gap-1"
        >
          <span>{showExclusions ? '▾' : '▸'}</span>
          <span>D2C Exclusions ({exclusions.length})</span>
        </button>
        {showExclusions && (
          <div className="mt-2 bg-white border border-gray-200 rounded-lg p-4">
            <p className="text-xs text-gray-500 mb-3">
              M-numbers in this list are permanently excluded from FBA restock plans.
              These are personalised or made-to-order items handled via the D2C workflow.
            </p>
            {exclusions.length > 0 && (
              <table className="w-full text-sm mb-4">
                <thead>
                  <tr className="border-b text-gray-500 text-xs">
                    <th className="text-left py-1.5 font-medium">M-Number</th>
                    <th className="text-left py-1.5 font-medium">Reason</th>
                    <th className="text-left py-1.5 font-medium">Added by</th>
                    <th className="w-8"></th>
                  </tr>
                </thead>
                <tbody>
                  {exclusions.map(ex => (
                    <tr key={ex.m_number} className="border-b last:border-0">
                      <td className="py-1.5 font-mono text-xs">{ex.m_number}</td>
                      <td className="py-1.5 text-gray-600">{ex.reason || '—'}</td>
                      <td className="py-1.5 text-gray-400 text-xs">{ex.added_by || '—'}</td>
                      <td className="py-1.5">
                        <button
                          onClick={() => handleRemoveExclusion(ex.m_number)}
                          className="text-red-400 hover:text-red-700 text-xs"
                          title="Remove exclusion"
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="M-number (e.g. M0634)"
                value={newExclusion}
                onChange={e => setNewExclusion(e.target.value)}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-40"
              />
              <input
                type="text"
                placeholder="Reason (optional)"
                value={newExclusionReason}
                onChange={e => setNewExclusionReason(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddExclusion()}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-56"
              />
              <button
                onClick={handleAddExclusion}
                className="bg-gray-800 text-white px-3 py-1 rounded text-sm hover:bg-gray-900"
              >
                Add exclusion
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Footer actions */}
      {selected.size > 0 && (
        <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 flex items-center justify-between">
          <span className="text-sm text-blue-800">
            <span className="font-semibold">{selected.size}</span> items selected &nbsp;·&nbsp;
            <span className="font-semibold">{totalSelectedUnits.toLocaleString()}</span> total units
          </span>
          <div className="flex gap-2">
            <button
              onClick={handleApprove}
              disabled={approving}
              className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {approving ? 'Approving…' : 'Approve quantities'}
            </button>
            <button
              onClick={handleCreateProduction}
              disabled={creatingPO}
              className="bg-green-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-green-700 disabled:opacity-50"
            >
              {creatingPO ? 'Creating…' : 'Create production orders'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
