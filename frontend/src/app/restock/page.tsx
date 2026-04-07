'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '@/lib/api'

const MARKETPLACES = ['GB', 'US', 'CA', 'AU', 'DE', 'FR']

interface RestockItem {
  id: number
  merchant_sku: string
  asin: string
  m_number: string
  product_name: string
  units_available: number
  units_inbound: number
  units_total: number
  days_of_supply_amazon: number | null
  units_sold_30d: number
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
  if (confidence === null) return <span className="text-gray-300">⚪</span>
  if (confidence >= 0.8) return <span title={`Confidence: ${(confidence * 100).toFixed(0)}%`}>🟢</span>
  if (confidence >= 0.5) return <span title={`Confidence: ${(confidence * 100).toFixed(0)}%`}>🟡</span>
  return <span title={`Confidence: ${(confidence * 100).toFixed(0)}%`}>🔴</span>
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

export default function RestockPage() {
  const [activeMarketplace, setActiveMarketplace] = useState('GB')
  const [items, setItems] = useState<RestockItem[]>([])
  const [summary, setSummary] = useState<PlanSummary | null>(null)
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [alertFilter, setAlertFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [editQtys, setEditQtys] = useState<Record<number, number>>({})
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [statusMsg, setStatusMsg] = useState('')
  const [approving, setApproving] = useState(false)
  const [creatingPO, setCreatingPO] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

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
      // Pre-fill editQtys with newsvendor_qty defaults
      const qtys: Record<number, number> = {}
      for (const item of data.items || []) {
        qtys[item.id] = item.approved_qty ?? item.newsvendor_qty ?? 0
      }
      setEditQtys(qtys)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [activeMarketplace, alertFilter, search])

  const checkSyncStatus = useCallback(async () => {
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
  }, [activeMarketplace, loadPlan])

  useEffect(() => {
    loadPlan()
    checkSyncStatus()
  }, [activeMarketplace])

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

  const toggleSelect = (id: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selected.size === items.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(items.map(i => i.id)))
    }
  }

  const handleApprove = async () => {
    if (selected.size === 0) return
    setApproving(true)
    const payload = [...selected].map(id => ({
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
            <span className="font-semibold text-gray-900">{summary.total_items}</span> items
          </span>
          <span>
            <span className="font-semibold text-red-600">{summary.action_items}</span> need action
          </span>
          <span>
            Newsvendor total:{' '}
            <span className="font-semibold text-gray-900">
              {summary.newsvendor_total_units.toLocaleString()} units
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
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b text-left">
                <th className="px-3 py-2 w-8">
                  <input
                    type="checkbox"
                    checked={selected.size === items.length && items.length > 0}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th className="px-3 py-2 font-semibold">M-number</th>
                <th className="px-3 py-2 font-semibold">SKU</th>
                <th className="px-3 py-2 font-semibold">Alert</th>
                <th className="px-3 py-2 font-semibold text-right">FBA Stock</th>
                <th className="px-3 py-2 font-semibold text-right">30d Sales</th>
                <th className="px-3 py-2 font-semibold text-right">DoS</th>
                <th className="px-3 py-2 font-semibold text-right">Amazon Rec.</th>
                <th className="px-3 py-2 font-semibold text-right">Newsvendor</th>
                <th className="px-3 py-2 font-semibold text-right w-28">Send qty</th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => (
                <tr
                  key={item.id}
                  className={`border-b cursor-pointer hover:bg-gray-50 ${
                    selected.has(item.id) ? 'bg-blue-50' : ''
                  } ${item.alert === 'out_of_stock' ? 'border-l-2 border-l-red-400' : ''}`}
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
                  <td className="px-3 py-2 text-right">
                    {item.units_available}
                    {item.units_inbound > 0 && (
                      <span className="text-gray-400 text-xs ml-1">+{item.units_inbound}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">{item.units_sold_30d}</td>
                  <td className="px-3 py-2 text-right text-gray-500">
                    {item.days_of_supply_amazon !== null
                      ? `${item.days_of_supply_amazon}d`
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-600">
                    {item.amazon_recommended_qty ?? '—'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      title={item.newsvendor_notes || 'No notes'}
                      className="cursor-help"
                    >
                      {item.newsvendor_qty ?? '—'}{' '}
                      <ConfidenceDot confidence={item.newsvendor_confidence} />
                    </span>
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
