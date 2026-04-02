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
}

interface Stats {
  pending: number
  in_progress: number
  made: number
  dispatched: number
  total: number
}

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
  const [filter, setFilter] = useState('pending')
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  const loadOrders = useCallback(() => {
    const params = new URLSearchParams({ page_size: '100' })
    if (filter) params.set('status', filter)

    Promise.all([
      api(`/api/dispatch/?${params}`).then(r => r.json()),
      api('/api/dispatch/stats/').then(r => r.json()),
    ]).then(([data, statsData]) => {
      setOrders(data.results || [])
      setStats(statsData)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [filter])

  useEffect(() => { loadOrders() }, [loadOrders])

  const markMade = async (id: number) => {
    await api(`/api/dispatch/${id}/mark-made/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    loadOrders()
    setMessage('Marked as made')
    setTimeout(() => setMessage(''), 3000)
  }

  const markDispatched = async (id: number) => {
    await api(`/api/dispatch/${id}/mark-dispatched/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    loadOrders()
    setMessage('Marked as dispatched')
    setTimeout(() => setMessage(''), 3000)
  }

  const formatDate = (d: string | null) => {
    if (!d) return ''
    return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold">Dispatch Queue</h2>
          {message && <span className="text-green-600 text-sm font-medium">{message}</span>}
        </div>
        <div className="flex items-center gap-3">
          <a href="/imports" className="text-blue-600 text-sm hover:underline">Upload Zenstores CSV</a>
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          >
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="in_progress">In Progress</option>
            <option value="made">Made</option>
            <option value="dispatched">Dispatched</option>
          </select>
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Pending</p>
            <p className="text-2xl font-bold text-yellow-600">{stats.pending}</p>
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

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : orders.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          No {filter || ''} orders. Upload a Zenstores CSV from the <a href="/imports" className="text-blue-600 hover:underline">Import</a> page.
        </div>
      ) : (
        <div className="space-y-3">
          {orders.map(order => (
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
                  {order.status === 'pending' && (
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
                <span className="text-gray-600 flex-1">{order.description}</span>
                <span className="text-gray-500">x{order.quantity}</span>
              </div>
              {order.is_personalised && (
                <p className="text-xs text-purple-600 mt-1">{order.personalisation_text}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
