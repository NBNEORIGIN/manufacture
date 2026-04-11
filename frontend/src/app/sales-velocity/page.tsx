'use client'

import { useEffect, useMemo, useState, useCallback } from 'react'
import { api } from '@/lib/api'

// ─── Types ─────────────────────────────────────────────────────────────────

interface StatusPayload {
  shadow_mode_enabled: boolean
  write_enabled: boolean
  channel_status: Record<string, {
    last_success_at: string | null
    last_error_at: string | null
    last_error_message: string
  }>
  unacknowledged_drift_count: number
  unmatched_sku_count: number
  latest_snapshot_date: string | null
  ebay_oauth: { connected: boolean; expires_at: string | null }
}

interface HistoryRow {
  id: number
  product: number
  m_number: string
  description: string
  channel: string
  snapshot_date: string
  units_sold_30d: number
}

interface UnmatchedRow {
  id: number
  channel: string
  external_sku: string
  title: string
  units_sold_30d: number
  first_seen: string
  last_seen: string
  ignored: boolean
  resolved_to: number | null
}

interface ManualSaleRow {
  id: number
  product: number
  m_number: string
  quantity: number
  sale_date: string
  channel: string
  notes: string
  entered_by: number | null
  entered_by_username: string | null
  created_at: string
}

interface DriftAlertRow {
  id: number
  product: number
  m_number: string
  detected_at: string
  current_velocity: number
  rolling_avg_velocity: number
  variance_pct: number
  acknowledged: boolean
  acknowledged_at: string | null
}

interface ShadowDiffRow {
  product_id: number
  m_number: string
  current_stock_sixty_day_sales: number
  api_30d_times_2: number
  variance_pct: number
}

// ─── Helpers ───────────────────────────────────────────────────────────────

const CHANNELS: Array<{ code: string; label: string }> = [
  { code: 'amazon_uk', label: 'UK' },
  { code: 'amazon_us', label: 'US' },
  { code: 'amazon_ca', label: 'CA' },
  { code: 'amazon_au', label: 'AU' },
  { code: 'amazon_de', label: 'DE' },
  { code: 'amazon_fr', label: 'FR' },
  { code: 'amazon_es', label: 'ES' },
  { code: 'amazon_nl', label: 'NL' },
  { code: 'amazon_it', label: 'IT' },
  { code: 'etsy', label: 'Etsy' },
  { code: 'ebay', label: 'eBay' },
  { code: 'footfall', label: 'Footfall' },
]

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-GB', { hour12: false })
}

function channelPillColour(
  info: StatusPayload['channel_status'][string] | undefined,
): string {
  if (!info) return 'bg-gray-200 text-gray-600'
  if (info.last_error_at && (!info.last_success_at || info.last_error_at > info.last_success_at)) {
    return 'bg-red-200 text-red-900'
  }
  if (info.last_success_at) return 'bg-green-200 text-green-900'
  return 'bg-gray-200 text-gray-600'
}

// ─── Main page ─────────────────────────────────────────────────────────────

export default function SalesVelocityPage() {
  const [status, setStatus] = useState<StatusPayload | null>(null)
  const [history, setHistory] = useState<HistoryRow[]>([])
  const [unmatched, setUnmatched] = useState<UnmatchedRow[]>([])
  const [driftAlerts, setDriftAlerts] = useState<DriftAlertRow[]>([])
  const [shadowDiff, setShadowDiff] = useState<ShadowDiffRow[]>([])
  const [manualSales, setManualSales] = useState<ManualSaleRow[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshBusy, setRefreshBusy] = useState(false)

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [s, h, u, d, sd, ms] = await Promise.all([
        api('/api/sales-velocity/status/').then(r => r.json()),
        api('/api/sales-velocity/history/').then(r => r.json()),
        api('/api/sales-velocity/unmatched/').then(r => r.json()),
        api('/api/sales-velocity/drift-alerts/').then(r => r.json()),
        api('/api/sales-velocity/shadow-diff/').then(r => r.json()),
        api('/api/sales-velocity/manual-sales/').then(r => r.json()),
      ])
      setStatus(s)
      setHistory(h.results ?? h)
      setUnmatched(u.results ?? u)
      setDriftAlerts(d.results ?? d)
      setShadowDiff(sd.rows ?? [])
      setManualSales(ms.results ?? ms)
    } catch (e) {
      console.error('Failed to load sales velocity data', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  const handleRefresh = async () => {
    setRefreshBusy(true)
    try {
      const r = await api('/api/sales-velocity/refresh/', { method: 'POST' })
      if (r.ok) {
        // The refresh runs async — we can't block on it. Wait a few seconds
        // and reload.
        setTimeout(() => { loadAll(); setRefreshBusy(false) }, 3000)
      } else {
        setRefreshBusy(false)
      }
    } catch {
      setRefreshBusy(false)
    }
  }

  // Aggregate history into per-product rows with per-channel breakdown
  const productRows = useMemo(() => {
    const map = new Map<number, {
      product: number
      m_number: string
      description: string
      total: number
      per_channel: Record<string, number>
    }>()
    for (const row of history) {
      let entry = map.get(row.product)
      if (!entry) {
        entry = {
          product: row.product,
          m_number: row.m_number,
          description: row.description,
          total: 0,
          per_channel: {},
        }
        map.set(row.product, entry)
      }
      entry.total += row.units_sold_30d
      entry.per_channel[row.channel] = (entry.per_channel[row.channel] ?? 0) + row.units_sold_30d
    }
    return Array.from(map.values()).sort(
      (a, b) => b.total - a.total,
    )
  }, [history])

  if (loading && !status) {
    return <div className="p-6">Loading Sales Velocity…</div>
  }

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold" style={{ color: '#674ea7' }}>
          Sales Velocity
        </h1>
        <button
          onClick={handleRefresh}
          disabled={refreshBusy}
          className="px-4 py-2 bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
        >
          {refreshBusy ? 'Refreshing…' : 'Refresh now'}
        </button>
      </header>

      {status && <StatusBar status={status} />}
      {driftAlerts.length > 0 && (
        <DriftAlertPanel alerts={driftAlerts} onChange={loadAll} />
      )}
      {status?.shadow_mode_enabled && (
        <ShadowDiffPanel rows={shadowDiff} snapshotDate={status.latest_snapshot_date} />
      )}
      {unmatched.length > 0 && (
        <UnmatchedPanel rows={unmatched} onChange={loadAll} />
      )}
      <VelocityTable rows={productRows} />
      <FootfallForm existing={manualSales} onChange={loadAll} />
    </div>
  )
}

// ─── Status bar ────────────────────────────────────────────────────────────

function StatusBar({ status }: { status: StatusPayload }) {
  const modeBanner = status.shadow_mode_enabled
    ? <div className="p-2 bg-amber-100 border-l-4 border-amber-500 rounded">
        <strong>Shadow mode — writes disabled.</strong>{' '}
        The aggregator fills SalesVelocityHistory but does not update{' '}
        <code>StockLevel.sixty_day_sales</code>. Flip{' '}
        <code>SALES_VELOCITY_WRITE_ENABLED=True</code> in the backend{' '}
        <code>.env</code> and restart to cut over.
      </div>
    : <div className="p-2 bg-green-100 border-l-4 border-green-500 rounded">
        <strong>Live mode.</strong> The aggregator is writing through to{' '}
        <code>StockLevel.sixty_day_sales</code>.
      </div>

  return (
    <section className="space-y-3">
      {modeBanner}
      <div className="flex flex-wrap gap-2 items-center text-sm">
        <span className="text-gray-600">
          Last snapshot: <strong>{status.latest_snapshot_date || '—'}</strong>
        </span>
        {!status.ebay_oauth.connected && (
          <span className="px-2 py-1 bg-red-200 text-red-900 rounded">
            eBay: reauth required — visit /admin/oauth/ebay/connect
          </span>
        )}
        {CHANNELS.map(c => {
          const info = status.channel_status[c.code]
          return (
            <span
              key={c.code}
              className={`px-2 py-1 rounded text-xs ${channelPillColour(info)}`}
              title={info?.last_error_message || info?.last_success_at || ''}
            >
              {c.label}
            </span>
          )
        })}
      </div>
    </section>
  )
}

// ─── Drift alert panel ─────────────────────────────────────────────────────

function DriftAlertPanel({
  alerts, onChange,
}: { alerts: DriftAlertRow[]; onChange: () => void }) {
  const ack = async (id: number) => {
    await api(`/api/sales-velocity/drift-alerts/${id}/acknowledge/`, {
      method: 'POST',
    })
    onChange()
  }
  return (
    <section className="border-2 border-red-500 rounded p-3 bg-red-50">
      <h2 className="font-bold text-red-900 mb-2">
        Drift alerts ({alerts.length})
      </h2>
      <table className="w-full text-sm">
        <thead className="text-left text-gray-600">
          <tr>
            <th>M-number</th>
            <th>Current</th>
            <th>7-day avg</th>
            <th>Variance %</th>
            <th>Detected</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {alerts.map(a => (
            <tr key={a.id} className="border-t">
              <td>{a.m_number}</td>
              <td>{a.current_velocity}</td>
              <td>{a.rolling_avg_velocity}</td>
              <td>{a.variance_pct}%</td>
              <td className="text-xs text-gray-500">{fmtDate(a.detected_at)}</td>
              <td>
                <button
                  onClick={() => ack(a.id)}
                  className="px-2 py-1 bg-gray-200 hover:bg-gray-300 rounded text-xs"
                >
                  Acknowledge
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

// ─── Shadow diff panel ─────────────────────────────────────────────────────

function ShadowDiffPanel({
  rows, snapshotDate,
}: { rows: ShadowDiffRow[]; snapshotDate: string | null }) {
  const [sortBy, setSortBy] = useState<'variance' | 'm_number'>('variance')
  const sorted = useMemo(() => {
    const copy = [...rows]
    if (sortBy === 'variance') {
      copy.sort((a, b) => Math.abs(b.variance_pct) - Math.abs(a.variance_pct))
    } else {
      copy.sort((a, b) => a.m_number.localeCompare(b.m_number))
    }
    return copy
  }, [rows, sortBy])

  return (
    <section className="border rounded p-3 bg-amber-50">
      <h2 className="font-bold mb-2">Shadow vs Live diff — snapshot {snapshotDate || '—'}</h2>
      <p className="text-xs text-gray-600 mb-2">
        Eyeball this for N days before flipping SALES_VELOCITY_WRITE_ENABLED to True.
      </p>
      <div className="mb-2 text-sm">
        Sort by:{' '}
        <button
          onClick={() => setSortBy('variance')}
          className={sortBy === 'variance' ? 'font-bold underline' : 'underline'}
        >variance</button>
        {' | '}
        <button
          onClick={() => setSortBy('m_number')}
          className={sortBy === 'm_number' ? 'font-bold underline' : 'underline'}
        >M-number</button>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-gray-600">
          <tr>
            <th>M-number</th>
            <th>Current stock.sixty_day_sales</th>
            <th>API 30d × 2</th>
            <th>Variance %</th>
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, 100).map(r => (
            <tr key={r.product_id} className="border-t">
              <td>{r.m_number}</td>
              <td>{r.current_stock_sixty_day_sales}</td>
              <td>{r.api_30d_times_2}</td>
              <td className={Math.abs(r.variance_pct) > 20 ? 'text-red-700 font-bold' : ''}>
                {r.variance_pct}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > 100 && (
        <p className="text-xs text-gray-500 mt-2">
          Showing first 100 of {sorted.length} rows.
        </p>
      )}
    </section>
  )
}

// ─── Unmatched SKUs panel ──────────────────────────────────────────────────

function UnmatchedPanel({
  rows, onChange,
}: { rows: UnmatchedRow[]; onChange: () => void }) {
  const [expanded, setExpanded] = useState(true)

  const ignore = async (id: number) => {
    await api(`/api/sales-velocity/unmatched/${id}/ignore/`, { method: 'POST' })
    onChange()
  }

  const mapTo = async (id: number) => {
    const pid = prompt('Product ID to resolve to (numeric):')
    if (!pid) return
    const r = await api(`/api/sales-velocity/unmatched/${id}/map/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: Number(pid) }),
    })
    if (r.ok) onChange()
    else alert(`Map failed: ${r.status}`)
  }

  return (
    <section className="border rounded p-3">
      <button
        className="font-bold"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? '▾' : '▸'} Unmatched SKUs ({rows.length})
      </button>
      {expanded && (
        <table className="w-full text-sm mt-2">
          <thead className="text-left text-gray-600">
            <tr>
              <th>Channel</th>
              <th>External SKU</th>
              <th>30d units</th>
              <th>First seen</th>
              <th>Last seen</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-t">
                <td>{r.channel}</td>
                <td className="font-mono text-xs">{r.external_sku}</td>
                <td>{r.units_sold_30d}</td>
                <td className="text-xs text-gray-500">{r.first_seen}</td>
                <td className="text-xs text-gray-500">{r.last_seen}</td>
                <td>
                  <button
                    onClick={() => mapTo(r.id)}
                    className="px-2 py-1 bg-violet-200 hover:bg-violet-300 rounded text-xs mr-1"
                  >
                    Map
                  </button>
                  <button
                    onClick={() => ignore(r.id)}
                    className="px-2 py-1 bg-gray-200 hover:bg-gray-300 rounded text-xs"
                  >
                    Ignore
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

// ─── Main velocity table ───────────────────────────────────────────────────

function VelocityTable({
  rows,
}: {
  rows: Array<{
    product: number
    m_number: string
    description: string
    total: number
    per_channel: Record<string, number>
  }>
}) {
  return (
    <section>
      <h2 className="font-bold mb-2">Per-product velocity (latest snapshot)</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-gray-600 sticky top-0 bg-white">
            <tr>
              <th className="py-1">M-number</th>
              <th>Description</th>
              <th className="text-right">30-day</th>
              <th className="text-right">60-day est.</th>
              {CHANNELS.map(c => (
                <th key={c.code} className="text-right text-xs">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.product} className="border-t hover:bg-gray-50">
                <td className="py-1 font-mono">{r.m_number}</td>
                <td className="truncate max-w-xs">{r.description}</td>
                <td className="text-right font-bold">{r.total}</td>
                <td className="text-right">{r.total * 2}</td>
                {CHANNELS.map(c => (
                  <td key={c.code} className="text-right text-xs text-gray-600">
                    {r.per_channel[c.code] || ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && (
        <p className="text-gray-500 italic">
          No velocity data yet — run <code>refresh_sales_velocity</code> or wait
          for the 04:17 UTC daily schedule.
        </p>
      )}
    </section>
  )
}

// ─── Footfall form ─────────────────────────────────────────────────────────

function FootfallForm({
  existing, onChange,
}: { existing: ManualSaleRow[]; onChange: () => void }) {
  const [productId, setProductId] = useState('')
  const [qty, setQty] = useState('')
  const [saleDate, setSaleDate] = useState(
    new Date().toISOString().slice(0, 10),
  )
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    const r = await api('/api/sales-velocity/manual-sales/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product: Number(productId),
        quantity: Number(qty),
        sale_date: saleDate,
        channel: 'footfall',
        notes,
      }),
    })
    setBusy(false)
    if (r.ok) {
      setProductId('')
      setQty('')
      setNotes('')
      onChange()
    } else {
      alert(`Failed: ${r.status}`)
    }
  }

  const del = async (id: number) => {
    if (!confirm('Delete this manual sale?')) return
    await api(`/api/sales-velocity/manual-sales/${id}/`, { method: 'DELETE' })
    onChange()
  }

  return (
    <section className="border rounded p-3">
      <h2 className="font-bold mb-2">Footfall entry</h2>
      <form onSubmit={submit} className="flex flex-wrap gap-2 items-end mb-3">
        <label className="text-sm">
          Product ID
          <input
            type="number"
            value={productId}
            onChange={e => setProductId(e.target.value)}
            required
            className="block border rounded px-2 py-1"
          />
        </label>
        <label className="text-sm">
          Quantity
          <input
            type="number"
            min="1"
            value={qty}
            onChange={e => setQty(e.target.value)}
            required
            className="block border rounded px-2 py-1 w-20"
          />
        </label>
        <label className="text-sm">
          Date
          <input
            type="date"
            value={saleDate}
            onChange={e => setSaleDate(e.target.value)}
            required
            className="block border rounded px-2 py-1"
          />
        </label>
        <label className="text-sm flex-1 min-w-40">
          Notes
          <input
            type="text"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            className="block border rounded px-2 py-1 w-full"
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="px-3 py-1 bg-violet-600 text-white rounded disabled:opacity-50"
        >
          {busy ? 'Saving…' : 'Add'}
        </button>
      </form>
      {existing.length > 0 && (
        <div>
          <h3 className="text-sm font-bold mb-1">Recent entries</h3>
          <table className="w-full text-xs">
            <thead className="text-left text-gray-600">
              <tr>
                <th>M-number</th><th>Qty</th><th>Date</th><th>Notes</th><th>By</th><th></th>
              </tr>
            </thead>
            <tbody>
              {existing.slice(0, 10).map(r => (
                <tr key={r.id} className="border-t">
                  <td>{r.m_number}</td>
                  <td>{r.quantity}</td>
                  <td>{r.sale_date}</td>
                  <td className="truncate max-w-xs">{r.notes}</td>
                  <td>{r.entered_by_username || '—'}</td>
                  <td>
                    <button
                      onClick={() => del(r.id)}
                      className="text-red-600 hover:text-red-800"
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
