'use client'

/**
 * /pick — mobile-first warehouse picking screen.
 *
 * Designed for Jo / Ben / Ivan walking the warehouse with a phone. One screen,
 * one job: see what's ready to ship, walk to it, tap. No clutter — no import
 * pane, no analytics, no tabs. Sticky header with search; cards sorted by
 * M-number so the floor walk is consistent. Lives at /pick so the PWA
 * launches straight into it.
 *
 * Flow:
 *   1. List all open D2C orders that have a linked Product (i.e. pickable).
 *   2. Group by M-number — picker walks one location at a time.
 *   3. Tap a card to see the orders for that M-number.
 *   4. Tap "Picked" → fulfil-from-stock (or mark-dispatched if no stock).
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/api'

interface DispatchOrder {
  id: number
  order_id: string
  channel: string
  status: string
  m_number: string
  sku: string
  description: string
  quantity: number
  customer_name: string
  flags: string
  current_stock: number
  product_is_personalised: boolean
  can_fulfil_from_stock: boolean
  blank: string
  blank_family: string
}

type PickFilter = 'in_stock' | 'all'

export default function PickPage() {
  const [orders, setOrders] = useState<DispatchOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<PickFilter>('in_stock')
  const [busy, setBusy] = useState<Set<number>>(new Set())
  const [toast, setToast] = useState<{ kind: 'ok' | 'err'; msg: string } | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const loadOrders = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page_size: '500',
        status__in: 'pending,in_progress,made',
      })
      const res = await api(`/api/dispatch/?${params}`)
      const data = await res.json()
      setOrders(data.results || [])
    } catch {
      setToast({ kind: 'err', msg: 'Could not load orders' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadOrders() }, [loadOrders])

  const flash = (kind: 'ok' | 'err', msg: string) => {
    setToast({ kind, msg })
    setTimeout(() => setToast(null), 2200)
  }

  // Filter rules:
  //   in_stock: pickable now — has product, not personalised, stock > 0
  //   all: everything (incl. personalised, no stock — for completeness)
  const filtered = useMemo(() => {
    let rows = orders.filter(o => !o.product_is_personalised && o.m_number)
    if (filter === 'in_stock') {
      rows = rows.filter(o => o.current_stock >= o.quantity)
    }
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter(o =>
        o.m_number.toLowerCase().includes(q) ||
        o.sku.toLowerCase().includes(q) ||
        o.description.toLowerCase().includes(q) ||
        o.order_id.toLowerCase().includes(q),
      )
    }
    return rows
  }, [orders, filter, search])

  // Group by m_number → list of orders for that part
  const groups = useMemo(() => {
    const m = new Map<string, { m_number: string; description: string; blank: string; current_stock: number; orders: DispatchOrder[] }>()
    for (const o of filtered) {
      const existing = m.get(o.m_number)
      if (existing) {
        existing.orders.push(o)
      } else {
        m.set(o.m_number, {
          m_number: o.m_number,
          description: o.description,
          blank: o.blank,
          current_stock: o.current_stock,
          orders: [o],
        })
      }
    }
    return Array.from(m.values()).sort((a, b) => a.m_number.localeCompare(b.m_number))
  }, [filtered])

  const totalUnits = filtered.reduce((s, o) => s + o.quantity, 0)

  const dispatchOrder = async (id: number, mode: 'fulfil' | 'dispatch') => {
    setBusy(prev => new Set(prev).add(id))
    try {
      const url = mode === 'fulfil'
        ? `/api/dispatch/${id}/fulfil-from-stock/`
        : `/api/dispatch/${id}/mark-dispatched/`
      const res = await api(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (res.ok) {
        // Vibrate on success (PWA on Android) so the picker has tactile feedback
        if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
          try { navigator.vibrate(40) } catch { /* iOS swallows */ }
        }
        flash('ok', mode === 'fulfil' ? 'Picked & dispatched' : 'Dispatched')
        // Optimistic remove + reload
        setOrders(prev => prev.filter(o => o.id !== id))
        loadOrders()
      } else {
        const err = await res.json().catch(() => ({}))
        flash('err', err.error || `Failed (HTTP ${res.status})`)
      }
    } catch (e) {
      flash('err', 'Network error')
      console.error(e)
    } finally {
      setBusy(prev => { const s = new Set(prev); s.delete(id); return s })
    }
  }

  const toggleExpanded = (mn: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(mn)) next.delete(mn); else next.add(mn)
      return next
    })
  }

  return (
    <div className="-mx-6 -my-8 sm:mx-0 sm:my-0 min-h-[calc(100vh-3rem)] bg-slate-50">
      {/* Sticky header */}
      <div className="sticky top-12 z-30 bg-slate-50 border-b border-slate-200 px-4 pt-4 pb-3">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-lg font-bold text-slate-900">Pick</h1>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-500">
              <span className="font-bold text-slate-900">{filtered.length}</span> orders ·{' '}
              <span className="font-bold text-slate-900">{totalUnits}</span> units
            </span>
            <button
              onClick={loadOrders}
              disabled={loading}
              className="bg-slate-800 text-white text-xs px-3 py-1.5 rounded disabled:opacity-50"
            >
              {loading ? '…' : '↻'}
            </button>
          </div>
        </div>

        <input
          type="search"
          inputMode="search"
          autoComplete="off"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search M#, SKU, order ID…"
          className="w-full text-base border border-slate-300 rounded-lg px-3 py-2.5 mb-2 focus:outline-none focus:ring-2 focus:ring-slate-500"
        />

        <div className="flex gap-1.5">
          {([
            { key: 'in_stock', label: 'In stock' },
            { key: 'all',      label: 'All open' },
          ] as { key: PickFilter; label: string }[]).map(opt => (
            <button
              key={opt.key}
              onClick={() => setFilter(opt.key)}
              className={`flex-1 px-3 py-2 rounded-md text-sm font-semibold transition-colors ${
                filter === opt.key
                  ? 'bg-slate-900 text-white'
                  : 'bg-white border border-slate-200 text-slate-700'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className={`fixed top-24 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg shadow-lg text-sm font-medium ${
            toast.kind === 'ok'
              ? 'bg-emerald-700 text-white'
              : 'bg-rose-700 text-white'
          }`}
        >
          {toast.msg}
        </div>
      )}

      {/* Body */}
      <div className="px-3 py-4 space-y-2.5 pb-24">
        {loading && groups.length === 0 ? (
          <p className="text-center text-slate-400 mt-12">Loading…</p>
        ) : groups.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-lg p-8 text-center text-slate-500 mx-1 mt-6">
            <p className="text-base font-medium mb-1">Nothing to pick</p>
            <p className="text-sm">
              {filter === 'in_stock'
                ? 'No orders with stock available right now.'
                : 'No open generic orders.'}
            </p>
          </div>
        ) : (
          groups.map(g => {
            const isOpen = expanded.has(g.m_number)
            const totalQty = g.orders.reduce((s, o) => s + o.quantity, 0)
            const stockOk = g.current_stock >= totalQty
            const ordersCount = g.orders.length
            return (
              <div
                key={g.m_number}
                className="bg-white border border-slate-200 rounded-lg overflow-hidden shadow-sm"
              >
                {/* Group header — tap to expand */}
                <button
                  onClick={() => toggleExpanded(g.m_number)}
                  className="w-full flex items-center justify-between px-3 py-3 text-left active:bg-slate-100 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-xl font-mono font-bold text-slate-900 tracking-tight">
                        {g.m_number}
                      </span>
                      {g.blank && (
                        <span className="text-[10px] uppercase tracking-wide bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded font-semibold">
                          {g.blank}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 truncate pr-2">{g.description}</p>
                  </div>
                  <div className="flex flex-col items-end gap-0.5 ml-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                      stockOk
                        ? 'bg-emerald-100 text-emerald-800'
                        : 'bg-rose-100 text-rose-800'
                    }`}>
                      {g.current_stock} stock
                    </span>
                    <span className="text-xs text-slate-500 font-medium">
                      pick {totalQty}{ordersCount > 1 ? ` · ${ordersCount} orders` : ''}
                    </span>
                  </div>
                </button>

                {/* Expanded order list */}
                {isOpen && (
                  <div className="border-t border-slate-200 bg-slate-50 divide-y divide-slate-200">
                    {g.orders.map(o => {
                      const inFlight = busy.has(o.id)
                      const canFulfil = o.can_fulfil_from_stock
                      return (
                        <div key={o.id} className="px-3 py-3 flex items-center justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-mono text-slate-600 truncate">{o.order_id}</p>
                            <p className="text-xs text-slate-500">
                              {o.channel}
                              {o.flags && <span className="ml-1 px-1 py-0.5 bg-amber-100 text-amber-800 rounded text-[10px]">{o.flags}</span>}
                            </p>
                            <p className="text-xs text-slate-500 truncate">
                              {o.customer_name || '—'}
                            </p>
                          </div>
                          <div className="flex flex-col items-end gap-1">
                            <span className="text-base font-semibold text-slate-900">× {o.quantity}</span>
                            <button
                              onClick={() => dispatchOrder(o.id, canFulfil ? 'fulfil' : 'dispatch')}
                              disabled={inFlight}
                              className={`text-sm font-semibold px-4 py-2 rounded-md disabled:opacity-50 ${
                                canFulfil
                                  ? 'bg-emerald-700 text-white active:bg-emerald-800'
                                  : 'bg-blue-700 text-white active:bg-blue-800'
                              }`}
                              style={{ minWidth: 96, minHeight: 40 }}
                            >
                              {inFlight ? '…' : canFulfil ? 'Picked' : 'Dispatch'}
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
