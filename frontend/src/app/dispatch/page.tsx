'use client'

import { useEffect, useState, useCallback } from 'react'
import { api } from '@/lib/api'

interface DispatchOrder {
  id: number
  order_id: string
  channel: string
  order_date: string | null
  status: string
  m_number: string
  sku: string
  description: string
  quantity: number
  customer_name: string
  flags: string
  is_personalised: boolean
  personalisation_text: string
  line1: string
  notes: string
  completed_at: string | null
  // Phase 5 stock-aware fields
  current_stock: number
  product_is_personalised: boolean
  can_fulfil_from_stock: boolean
  blank: string
  blank_family: string
}

interface Stats {
  pending: number
  in_progress: number
  made: number
  dispatched: number
  total: number
  fulfillable: number
}

type Tab = 'ready' | 'needs_making' | 'personalised' | 'all'

const STATUS_COLOURS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  in_progress: 'bg-blue-100 text-blue-800',
  made: 'bg-green-100 text-green-800',
  dispatched: 'bg-gray-100 text-gray-600',
  cancelled: 'bg-red-100 text-red-800',
}

export default function DispatchPage() {
  const [orders, setOrders] = useState<DispatchOrder[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [tab, setTab] = useState<Tab>('ready')
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [fulfilling, setFulfilling] = useState<Set<number>>(new Set())

  const loadOrders = useCallback(() => {
    // For the smart tabs, load all pending/in_progress orders
    // For 'all' tab, respect the status filter
    const params = new URLSearchParams({ page_size: '200' })
    if (tab === 'all' && statusFilter) {
      params.set('status', statusFilter)
    } else if (tab !== 'all') {
      // Load pending + in_progress for the smart tabs
      params.set('status', 'pending')
    }

    Promise.all([
      api(`/api/dispatch/?${params}`).then(r => r.json()),
      api('/api/dispatch/stats/').then(r => r.json()),
    ]).then(([data, statsData]) => {
      setOrders(data.results || [])
      setStats(statsData)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [tab, statusFilter])

  useEffect(() => { loadOrders() }, [loadOrders])

  // Filter orders based on active tab
  const filteredOrders = orders.filter(order => {
    if (tab === 'ready') return order.can_fulfil_from_stock
    if (tab === 'needs_making') return !order.can_fulfil_from_stock && !order.product_is_personalised
    if (tab === 'personalised') return order.product_is_personalised
    return true // 'all' tab
  })

  // Group "needs making" orders by blank
  const groupedByBlank = tab === 'needs_making'
    ? filteredOrders.reduce<Record<string, DispatchOrder[]>>((acc, order) => {
        const key = order.blank || 'Unknown'
        if (!acc[key]) acc[key] = []
        acc[key].push(order)
        return acc
      }, {})
    : null

  const flash = (msg: string) => {
    setMessage(msg)
    setTimeout(() => setMessage(''), 3000)
  }

  const fulfilFromStock = async (id: number) => {
    setFulfilling(prev => new Set(prev).add(id))
    try {
      const resp = await api(`/api/dispatch/${id}/fulfil-from-stock/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (resp.ok) {
        flash('Fulfilled from stock')
        loadOrders()
      } else {
        const err = await resp.json()
        flash(err.error || 'Failed to fulfil')
      }
    } finally {
      setFulfilling(prev => { const s = new Set(prev); s.delete(id); return s })
    }
  }

  const bulkFulfil = async () => {
    const ids = filteredOrders.map(o => o.id)
    if (ids.length === 0) return
    setFulfilling(new Set(ids))
    try {
      const resp = await api('/api/dispatch/bulk-fulfil/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      })
      if (resp.ok) {
        const data = await resp.json()
        flash(`Fulfilled ${data.fulfilled.length} order(s)` +
          (data.failed.length ? `, ${data.failed.length} failed` : ''))
        loadOrders()
      }
    } finally {
      setFulfilling(new Set())
    }
  }

  const markMade = async (id: number) => {
    await api(`/api/dispatch/${id}/mark-made/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    loadOrders()
    flash('Marked as made')
  }

  const markDispatched = async (id: number) => {
    await api(`/api/dispatch/${id}/mark-dispatched/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    loadOrders()
    flash('Marked as dispatched')
  }

  const formatDate = (d: string | null) => {
    if (!d) return ''
    return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  }

  const readyCount = orders.filter(o => o.can_fulfil_from_stock).length
  const needsMakingCount = orders.filter(o => !o.can_fulfil_from_stock && !o.product_is_personalised).length
  const personalisedCount = orders.filter(o => o.product_is_personalised).length

  const TABS: { key: Tab; label: string; count: number }[] = [
    { key: 'ready', label: 'Ready to Ship', count: readyCount },
    { key: 'needs_making', label: 'Needs Making', count: needsMakingCount },
    { key: 'personalised', label: 'Personalised', count: personalisedCount },
    { key: 'all', label: 'All', count: orders.length },
  ]

  const renderOrderCard = (order: DispatchOrder) => (
    <div key={order.id} className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm">{order.order_id}</span>
          <span className={`text-xs px-2 py-0.5 rounded ${STATUS_COLOURS[order.status]}`}>
            {order.status}
          </span>
          {order.flags && (
            <span className="text-xs bg-orange-100 text-orange-800 px-2 py-0.5 rounded">
              {order.flags}
            </span>
          )}
          <span className="text-xs text-gray-400">{order.channel}</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Stock badge */}
          {!order.product_is_personalised && order.m_number && (
            <span className={`text-xs px-2 py-0.5 rounded ${
              order.current_stock > 0
                ? 'bg-emerald-50 text-emerald-700'
                : 'bg-red-50 text-red-700'
            }`}>
              {order.current_stock > 0 ? `Stock: ${order.current_stock}` : 'No Stock'}
            </span>
          )}
          {/* Action buttons */}
          {order.can_fulfil_from_stock && order.status === 'pending' && (
            <button
              onClick={() => fulfilFromStock(order.id)}
              disabled={fulfilling.has(order.id)}
              className="bg-emerald-600 text-white px-3 py-1 rounded text-xs hover:bg-emerald-700 disabled:opacity-50"
            >
              {fulfilling.has(order.id) ? 'Fulfilling...' : 'Fulfil'}
            </button>
          )}
          {order.status === 'pending' && !order.can_fulfil_from_stock && !order.product_is_personalised && (
            <button
              onClick={() => markMade(order.id)}
              className="bg-green-600 text-white px-3 py-1 rounded text-xs hover:bg-green-700"
            >
              Mark Made
            </button>
          )}
          {order.status === 'made' && (
            <button
              onClick={() => markDispatched(order.id)}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
            >
              Mark Dispatched
            </button>
          )}
          <span className="text-xs text-gray-400">{formatDate(order.order_date)}</span>
        </div>
      </div>
      <div className="flex items-center gap-4 text-sm">
        <span className="font-mono font-medium">{order.m_number || order.sku}</span>
        {order.blank && (
          <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
            {order.blank}
          </span>
        )}
        <span className="text-gray-600 flex-1">{order.description}</span>
        <span className="text-gray-500">x{order.quantity}</span>
      </div>
      {order.is_personalised && (
        <p className="text-xs text-purple-600 mt-1">{order.personalisation_text}</p>
      )}
    </div>
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold">Dispatch Queue</h2>
          {message && <span className="text-green-600 text-sm font-medium">{message}</span>}
        </div>
        <div className="flex items-center gap-3">
          <a href="/imports" className="text-blue-600 text-sm hover:underline">Upload Zenstores CSV</a>
          {tab === 'all' && (
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="border rounded px-3 py-2 text-sm"
            >
              <option value="">All Statuses</option>
              <option value="pending">Pending</option>
              <option value="in_progress">In Progress</option>
              <option value="made">Made</option>
              <option value="dispatched">Dispatched</option>
            </select>
          )}
        </div>
      </div>

      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Pending</p>
            <p className="text-2xl font-bold text-yellow-600">{stats.pending}</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Fulfillable</p>
            <p className="text-2xl font-bold text-emerald-600">{stats.fulfillable}</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">In Progress</p>
            <p className="text-2xl font-bold text-blue-600">{stats.in_progress}</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Made</p>
            <p className="text-2xl font-bold text-green-600">{stats.made}</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Dispatched</p>
            <p className="text-2xl font-bold text-gray-600">{stats.dispatched}</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Total</p>
            <p className="text-2xl font-bold">{stats.total}</p>
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex items-center gap-1 mb-6 border-b">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
            <span className={`ml-1.5 text-xs px-1.5 py-0.5 rounded-full ${
              tab === t.key ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
            }`}>
              {t.count}
            </span>
          </button>
        ))}
      </div>

      {/* Bulk actions */}
      {tab === 'ready' && readyCount > 0 && (
        <div className="flex items-center gap-3 mb-4">
          <button
            onClick={bulkFulfil}
            disabled={fulfilling.size > 0}
            className="bg-emerald-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-emerald-700 disabled:opacity-50"
          >
            {fulfilling.size > 0 ? 'Fulfilling...' : `Fulfil All (${readyCount})`}
          </button>
          <span className="text-xs text-gray-400">
            Ships from shelf — stock will be deducted automatically
          </span>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : filteredOrders.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          {tab === 'ready' && 'No orders fulfillable from stock right now.'}
          {tab === 'needs_making' && 'No orders waiting to be made.'}
          {tab === 'personalised' && 'No personalised orders in the queue.'}
          {tab === 'all' && (
            <>No {statusFilter || ''} orders. Upload a Zenstores CSV from the <a href="/imports" className="text-blue-600 hover:underline">Import</a> page.</>
          )}
        </div>
      ) : tab === 'needs_making' && groupedByBlank ? (
        /* Grouped by blank for needs-making tab */
        <div className="space-y-6">
          {Object.entries(groupedByBlank)
            .sort(([, a], [, b]) => b.length - a.length)
            .map(([blank, blankOrders]) => (
            <div key={blank}>
              <div className="flex items-center gap-3 mb-2">
                <h3 className="text-sm font-bold text-gray-700">{blank}</h3>
                <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded">
                  {blankOrders.reduce((sum, o) => sum + o.quantity, 0)} units across {blankOrders.length} order(s)
                </span>
              </div>
              <div className="space-y-3">
                {blankOrders.map(renderOrderCard)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {filteredOrders.map(renderOrderCard)}
        </div>
      )}
    </div>
  )
}
