'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'

/**
 * Combined D2C page (Toby review post-17):
 *  - Collapsible Zenstores import pane at the top (drag-and-drop → auto-preview)
 *  - Dispatch queue as the main surface (Ready / Needs Making / Personalised / All)
 *  - Collapsible Personalised exclusions list at the bottom
 *
 * Replaces the former /dispatch page, which now redirects here.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

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

interface ZenstoresPreview {
  order_id: string
  sku: string
  m_number: string
  description: string
  quantity: number
  flags: string
  channel: string
}

interface Exclusion {
  m_number: string
  reason: string
  added_by: string
  created_at: string
}

type Tab = 'ready' | 'needs_making' | 'personalised' | 'all'

// ─────────────────────────────────────────────────────────────────────────────
// Styles — keep badges neutral, no cartoon colours on status text
// ─────────────────────────────────────────────────────────────────────────────

const STATUS_COLOURS: Record<string, string> = {
  pending: 'bg-amber-50 text-amber-800 border border-amber-200',
  in_progress: 'bg-sky-50 text-sky-800 border border-sky-200',
  made: 'bg-emerald-50 text-emerald-800 border border-emerald-200',
  dispatched: 'bg-slate-100 text-slate-600 border border-slate-200',
  cancelled: 'bg-rose-50 text-rose-800 border border-rose-200',
}

// ─────────────────────────────────────────────────────────────────────────────
// Icons (inline SVG, consistent style)
// ─────────────────────────────────────────────────────────────────────────────

function IconUpload({ className = 'h-10 w-10' }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
         strokeWidth={1.4} stroke="currentColor" className={className}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 7.5m0 0L7.5 12M12 7.5V21" />
    </svg>
  )
}

function IconChevron({ open }: { open: boolean }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
         strokeWidth={2} stroke="currentColor"
         className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-90' : ''}`}>
      <path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
    </svg>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Import pane
// ─────────────────────────────────────────────────────────────────────────────

function ZenstoresImport({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [orders, setOrders] = useState<ZenstoresPreview[]>([])
  const [skipped, setSkipped] = useState<{ sku: string; reason: string }[]>([])
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [dragging, setDragging] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const dragCounter = useRef(0)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const runPreview = useCallback(async (f: File) => {
    setPreviewing(true)
    setError('')
    setSuccess('')
    setOrders([])
    setSkipped([])

    const formData = new FormData()
    formData.append('file', f)
    formData.append('report_type', 'zenstores')

    try {
      const res = await api('/api/imports/upload/', { method: 'POST', body: formData })
      const data = await res.json()
      if (!res.ok) {
        setError(data.error || 'Upload failed — check the file format')
        return
      }
      const items: ZenstoresPreview[] = data.changes || []
      setOrders(items)
      setSkipped(data.skipped || [])
      if (items.length === 0 && (data.skipped || []).length === 0) {
        setError('No orders parsed — check the CSV format')
      }
    } catch {
      setError('Upload failed — check the file format')
    } finally {
      setPreviewing(false)
    }
  }, [])

  const handleFile = useCallback((f: File | null, autoPreview = false) => {
    setFile(f)
    setOrders([])
    setSkipped([])
    setError('')
    setSuccess('')
    if (f && autoPreview) {
      // eslint-disable-next-line @typescript-eslint/no-floating-promises
      runPreview(f)
    }
  }, [runPreview])

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current++
    if (e.dataTransfer.items?.length) setDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current--
    if (dragCounter.current === 0) setDragging(false)
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragging(false)
    dragCounter.current = 0

    const files = e.dataTransfer.files
    if (files.length > 0) {
      const f = files[0]
      const ext = f.name.toLowerCase().split('.').pop()
      if (['csv', 'tsv', 'txt'].includes(ext || '')) {
        // Auto-preview on drop
        handleFile(f, true)
      } else {
        setError('Only CSV, TSV, or TXT files are supported')
      }
    }
  }, [handleFile])

  const confirmImport = async () => {
    if (!file) return
    setConfirming(true)
    setError('')

    const formData = new FormData()
    formData.append('file', file)
    formData.append('report_type', 'zenstores')
    formData.append('confirm', 'true')

    try {
      const res = await api('/api/imports/upload/', { method: 'POST', body: formData })
      const data = await res.json()
      if (!res.ok) {
        setError(data.error || 'Import failed')
        return
      }
      setSuccess(`Imported ${data.changes.length} orders to the dispatch queue`)
      setOrders([])
      setSkipped([])
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      onImported()
      setTimeout(() => setSuccess(''), 5000)
    } catch {
      setError('Import failed')
    } finally {
      setConfirming(false)
    }
  }

  return (
    <section className="bg-white rounded-lg border border-slate-200 mb-6">
      <button
        type="button"
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <IconChevron open={!collapsed} />
          <h3 className="text-sm font-semibold text-slate-900">Zenstores Order Import</h3>
          {file && (
            <span className="text-xs text-slate-500">· {file.name}</span>
          )}
        </div>
        <span className="text-xs text-slate-400">
          Drop a CSV to preview instantly
        </span>
      </button>

      {!collapsed && (
        <div className="px-5 pb-5">
          <div
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-md p-6 text-center cursor-pointer transition-colors ${
              dragging
                ? 'border-blue-500 bg-blue-50'
                : file
                  ? 'border-emerald-300 bg-emerald-50'
                  : 'border-slate-300 hover:border-slate-400 hover:bg-slate-50'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.tsv,.txt"
              onChange={e => handleFile(e.target.files?.[0] || null, true)}
              className="hidden"
            />
            <div className="flex flex-col items-center gap-2">
              <IconUpload className="h-8 w-8 text-slate-400" />
              {file ? (
                <>
                  <p className="text-sm font-medium text-emerald-800">{file.name}</p>
                  <p className="text-xs text-slate-500">
                    {(file.size / 1024).toFixed(1)} KB — click or drop to replace
                  </p>
                </>
              ) : (
                <>
                  <p className="text-sm text-slate-700">
                    <span className="font-medium text-blue-700">Click to browse</span>
                    {' '}or drag and drop your Zenstores CSV
                  </p>
                  <p className="text-xs text-slate-400">CSV, TSV, or TXT</p>
                </>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 mt-3">
            {file && !orders.length && (
              <button
                onClick={() => file && runPreview(file)}
                disabled={previewing}
                className="bg-slate-900 text-white px-3 py-1.5 rounded text-sm font-medium hover:bg-slate-800 disabled:opacity-50"
              >
                {previewing ? 'Parsing…' : 'Preview'}
              </button>
            )}
            {file && (
              <button
                onClick={() => { setFile(null); setOrders([]); setSkipped([]); setError(''); setSuccess(''); if (fileInputRef.current) fileInputRef.current.value = '' }}
                className="text-slate-500 hover:text-slate-700 text-xs"
              >
                Clear
              </button>
            )}
            {previewing && <span className="text-xs text-slate-400">Previewing…</span>}
          </div>

          {error && <p className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded px-3 py-2 mt-3">{error}</p>}
          {success && (
            <p className="text-sm text-emerald-800 bg-emerald-50 border border-emerald-200 rounded px-3 py-2 mt-3">
              {success}
            </p>
          )}

          {(orders.length > 0 || skipped.length > 0) && (
            <div className="border border-slate-200 rounded mt-4 overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 bg-slate-50 border-b border-slate-200">
                <p className="text-sm text-slate-700">
                  <span className="font-semibold">{orders.length}</span> new orders parsed
                  {skipped.length > 0 && (
                    <span className="text-slate-500 ml-2">· {skipped.length} already imported</span>
                  )}
                </p>
                {orders.length > 0 && (
                  <button
                    onClick={confirmImport}
                    disabled={confirming}
                    className="bg-emerald-700 text-white px-3 py-1.5 rounded text-sm font-medium hover:bg-emerald-800 disabled:opacity-50"
                  >
                    {confirming ? 'Importing…' : `Import ${orders.length} orders`}
                  </button>
                )}
              </div>

              {orders.length > 0 && (
                <div className="overflow-x-auto max-h-80">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 border-b border-slate-200 text-left sticky top-0">
                      <tr>
                        <th className="px-3 py-2 font-semibold text-slate-600">Order ID</th>
                        <th className="px-3 py-2 font-semibold text-slate-600">SKU</th>
                        <th className="px-3 py-2 font-semibold text-slate-600">M#</th>
                        <th className="px-3 py-2 font-semibold text-slate-600">Description</th>
                        <th className="px-3 py-2 font-semibold text-slate-600 text-right">Qty</th>
                        <th className="px-3 py-2 font-semibold text-slate-600">Channel</th>
                        <th className="px-3 py-2 font-semibold text-slate-600">Flags</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.map((o, i) => (
                        <tr key={i} className="border-b border-slate-100 last:border-0">
                          <td className="px-3 py-2 font-mono text-xs">{o.order_id}</td>
                          <td className="px-3 py-2 font-mono text-xs">{o.sku}</td>
                          <td className="px-3 py-2 font-mono text-xs text-slate-500">{o.m_number || '—'}</td>
                          <td className="px-3 py-2 text-slate-700 max-w-xs truncate" title={o.description}>{o.description}</td>
                          <td className="px-3 py-2 text-right">{o.quantity}</td>
                          <td className="px-3 py-2 text-xs text-slate-500">{o.channel}</td>
                          <td className="px-3 py-2 text-xs text-slate-500">{o.flags}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {skipped.length > 0 && (
                <details className="text-sm px-3 py-2 bg-slate-50">
                  <summary className="cursor-pointer text-slate-500">
                    {skipped.length} skipped items
                  </summary>
                  <div className="mt-2 max-h-40 overflow-y-auto">
                    {skipped.slice(0, 40).map((s, i) => (
                      <p key={i} className="text-slate-400">{s.sku}: {s.reason}</p>
                    ))}
                  </div>
                </details>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Personalised exclusions (collapsible footer panel)
// ─────────────────────────────────────────────────────────────────────────────

function PersonalisedExclusions({ exclusions }: { exclusions: Exclusion[] }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="bg-white rounded-lg border border-slate-200 mt-6">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <IconChevron open={open} />
          <h3 className="text-sm font-semibold text-slate-900">Personalised products (D2C only)</h3>
          <span className="text-xs text-slate-500">· {exclusions.length} items</span>
        </div>
        <span className="text-xs text-slate-400">Excluded from FBA restock planning</span>
      </button>
      {open && (
        <div className="px-5 pb-5">
          {exclusions.length === 0 ? (
            <p className="text-sm text-slate-400">No personalised products configured.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500 text-xs">
                  <th className="text-left py-2 font-medium">M-Number</th>
                  <th className="text-left py-2 font-medium">Reason</th>
                  <th className="text-left py-2 font-medium">Added by</th>
                </tr>
              </thead>
              <tbody>
                {exclusions.map(ex => (
                  <tr key={ex.m_number} className="border-b border-slate-100 last:border-0">
                    <td className="py-2 font-mono text-xs">{ex.m_number}</td>
                    <td className="py-2 text-slate-600">{ex.reason || '—'}</td>
                    <td className="py-2 text-slate-400 text-xs">{ex.added_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export default function D2CPage() {
  const [orders, setOrders] = useState<DispatchOrder[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [exclusions, setExclusions] = useState<Exclusion[]>([])
  const [tab, setTab] = useState<Tab>('ready')
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [fulfilling, setFulfilling] = useState<Set<number>>(new Set())

  const loadOrders = useCallback(() => {
    const params = new URLSearchParams({ page_size: '500' })
    if (tab === 'all' && statusFilter) {
      params.set('status', statusFilter)
    } else if (tab !== 'all') {
      params.set('status__in', 'pending,in_progress,made')
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

  const loadExclusions = useCallback(() => {
    api('/api/restock/exclusions/')
      .then(r => r.json())
      .then(d => setExclusions(d.exclusions || []))
      .catch(() => {})
  }, [])

  useEffect(() => { loadOrders() }, [loadOrders])
  useEffect(() => { loadExclusions() }, [loadExclusions])

  const flash = (msg: string) => {
    setMessage(msg)
    setTimeout(() => setMessage(''), 3000)
  }

  const filteredOrders = orders.filter(order => {
    if (tab === 'ready') {
      return order.status === 'made' || (order.status !== 'made' && order.can_fulfil_from_stock)
    }
    if (tab === 'needs_making') {
      return order.status !== 'made' && !order.can_fulfil_from_stock && !order.product_is_personalised
    }
    if (tab === 'personalised') {
      return order.product_is_personalised && order.status !== 'dispatched'
    }
    return true
  })

  const groupedByBlank = tab === 'needs_making'
    ? filteredOrders.reduce<Record<string, DispatchOrder[]>>((acc, order) => {
        const key = order.blank || 'Unknown'
        if (!acc[key]) acc[key] = []
        acc[key].push(order)
        return acc
      }, {})
    : null

  const fulfilFromStock = async (id: number) => {
    setFulfilling(prev => new Set(prev).add(id))
    try {
      const resp = await api(`/api/dispatch/${id}/fulfil-from-stock/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (resp.ok) { flash('Fulfilled from stock'); loadOrders() }
      else { const err = await resp.json(); flash(err.error || 'Failed to fulfil') }
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

  const readyCount = orders.filter(o =>
    o.status === 'made' || (o.status !== 'made' && o.can_fulfil_from_stock)
  ).length
  const needsMakingCount = orders.filter(o =>
    o.status !== 'made' && !o.can_fulfil_from_stock && !o.product_is_personalised
  ).length
  const personalisedCount = orders.filter(o =>
    o.product_is_personalised && o.status !== 'dispatched'
  ).length

  const TABS: { key: Tab; label: string; count: number }[] = [
    { key: 'ready', label: 'Ready to ship', count: readyCount },
    { key: 'needs_making', label: 'Needs making', count: needsMakingCount },
    { key: 'personalised', label: 'Personalised', count: personalisedCount },
    { key: 'all', label: 'All', count: orders.length },
  ]

  const renderOrderCard = (order: DispatchOrder) => (
    <div key={order.id} className="bg-white rounded-md border border-slate-200 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className="font-mono text-sm text-slate-700">{order.order_id}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_COLOURS[order.status]}`}>
            {order.status.replace('_', ' ')}
          </span>
          {order.flags && (
            <span className="text-xs bg-orange-50 text-orange-800 border border-orange-200 px-1.5 py-0.5 rounded">
              {order.flags}
            </span>
          )}
          <span className="text-xs text-slate-400">{order.channel}</span>
        </div>
        <div className="flex items-center gap-2">
          {!order.product_is_personalised && (
            <span className={`text-xs px-1.5 py-0.5 rounded border ${
              order.current_stock > 0
                ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                : 'bg-rose-50 text-rose-800 border-rose-200'
            }`}>
              Stock: {order.current_stock}
            </span>
          )}
          {order.can_fulfil_from_stock && order.status === 'pending' && (
            <button
              onClick={() => fulfilFromStock(order.id)}
              disabled={fulfilling.has(order.id)}
              className="bg-emerald-700 text-white px-3 py-1 rounded text-xs hover:bg-emerald-800 disabled:opacity-50"
            >
              {fulfilling.has(order.id) ? 'Fulfilling…' : 'Fulfil'}
            </button>
          )}
          {order.status === 'pending' && !order.can_fulfil_from_stock && !order.product_is_personalised && (
            <button
              onClick={() => markMade(order.id)}
              className="bg-slate-800 text-white px-3 py-1 rounded text-xs hover:bg-slate-900"
            >
              Mark made
            </button>
          )}
          {order.status === 'made' && (
            <button
              onClick={() => markDispatched(order.id)}
              className="bg-blue-700 text-white px-3 py-1 rounded text-xs hover:bg-blue-800"
            >
              Mark dispatched
            </button>
          )}
          <span className="text-xs text-slate-400">{formatDate(order.order_date)}</span>
        </div>
      </div>
      <div className="flex items-center gap-3 text-sm">
        <span className="font-mono font-medium text-slate-800">{order.m_number || order.sku}</span>
        {order.blank && (
          <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">
            {order.blank}
          </span>
        )}
        <span className="text-slate-600 flex-1">{order.description}</span>
        <span className="text-slate-500">× {order.quantity}</span>
      </div>
      {order.is_personalised && (
        <p className="text-xs text-violet-700 mt-1">{order.personalisation_text}</p>
      )}
    </div>
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-2xl font-semibold text-slate-900">Direct-to-Consumer</h2>
        {message && (
          <span className="text-sm font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-3 py-1">
            {message}
          </span>
        )}
      </div>

      {/* Zenstores import pane */}
      <ZenstoresImport onImported={loadOrders} />

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-5">
          <StatCard label="Pending" value={stats.pending} tone="slate" />
          <StatCard label="Fulfillable" value={stats.fulfillable} tone="emerald" />
          <StatCard label="In progress" value={stats.in_progress} tone="slate" />
          <StatCard label="Made" value={stats.made} tone="slate" />
          <StatCard label="Dispatched" value={stats.dispatched} tone="slate" />
          <StatCard label="Total" value={stats.total} tone="slate" />
        </div>
      )}

      {/* Tabs + (optional) status filter */}
      <div className="flex items-end justify-between mb-4 border-b border-slate-200">
        <div className="flex items-center gap-1">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3.5 py-2 text-sm font-medium border-b-2 transition-colors ${
                tab === t.key
                  ? 'border-slate-900 text-slate-900'
                  : 'border-transparent text-slate-500 hover:text-slate-800'
              }`}
            >
              {t.label}
              <span className={`ml-1.5 text-xs px-1.5 py-0.5 rounded ${
                tab === t.key ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600'
              }`}>
                {t.count}
              </span>
            </button>
          ))}
        </div>
        {tab === 'all' && (
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="border border-slate-300 rounded px-2 py-1 text-sm mb-1.5"
          >
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="in_progress">In progress</option>
            <option value="made">Made</option>
            <option value="dispatched">Dispatched</option>
          </select>
        )}
      </div>

      {/* Bulk action */}
      {tab === 'ready' && readyCount > 0 && (
        <div className="flex items-center gap-3 mb-4">
          <button
            onClick={bulkFulfil}
            disabled={fulfilling.size > 0}
            className="bg-emerald-700 text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-emerald-800 disabled:opacity-50"
          >
            {fulfilling.size > 0 ? 'Fulfilling…' : `Fulfil all (${readyCount})`}
          </button>
          <span className="text-xs text-slate-500">
            Ships from shelf — stock deducted automatically
          </span>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <p className="text-slate-400 text-sm">Loading…</p>
      ) : filteredOrders.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-md p-8 text-center text-slate-500">
          {tab === 'ready' && 'No orders ready to ship right now.'}
          {tab === 'needs_making' && 'No orders waiting to be made.'}
          {tab === 'personalised' && 'No personalised orders in the queue.'}
          {tab === 'all' && `No ${statusFilter || ''} orders. Drop a Zenstores CSV above to import.`}
        </div>
      ) : tab === 'needs_making' && groupedByBlank ? (
        <div className="space-y-5">
          {Object.entries(groupedByBlank)
            .sort(([, a], [, b]) => b.length - a.length)
            .map(([blank, blankOrders]) => (
            <div key={blank}>
              <div className="flex items-center gap-3 mb-2">
                <h3 className="text-sm font-semibold text-slate-700">{blank}</h3>
                <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                  {blankOrders.reduce((sum, o) => sum + o.quantity, 0)} units across {blankOrders.length} orders
                </span>
              </div>
              <div className="space-y-2">
                {blankOrders.map(renderOrderCard)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {filteredOrders.map(renderOrderCard)}
        </div>
      )}

      {/* Personalised exclusions */}
      <PersonalisedExclusions exclusions={exclusions} />
    </div>
  )
}

function StatCard({ label, value, tone }: { label: string; value: number; tone: 'slate' | 'emerald' }) {
  const valueClass = tone === 'emerald' ? 'text-emerald-700' : 'text-slate-900'
  return (
    <div className="bg-white rounded-md border border-slate-200 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-xl font-semibold ${valueClass}`}>{value}</p>
    </div>
  )
}
