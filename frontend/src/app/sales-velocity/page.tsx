'use client'

import { useEffect, useMemo, useState, useCallback } from 'react'
import { api } from '@/lib/api'

// ─── Types ─────────────────────────────────────────────────────────────────

interface SummaryPayload {
  total_units_on_hand: number
  total_sixty_day_target: number
  coverage_pct: number
  products_need_making: number
  out_of_stock_count: number
  surplus_count: number
  latest_snapshot_date: string | null
  last_sync_at: string | null
  shadow_mode_enabled: boolean
}

interface TableRow {
  product_id: number
  m_number: string
  description: string
  blank: string
  material: string
  current_stock: number
  sixty_day_target: number
  deficit: number
  velocity_30d: number
  velocity_60d_est: number
  status: 'OUT_OF_STOCK' | 'LOW' | 'OK' | 'SURPLUS'
  channels: string
  channel_detail: Record<string, number>
  wip_count: number
  image_url: string
}

interface UnmatchedRow {
  id: number; channel: string; external_sku: string; title: string
  units_sold_30d: number; first_seen: string; last_seen: string
  ignored: boolean; resolved_to: number | null
}

interface DriftAlertRow {
  id: number; product: number; m_number: string; detected_at: string
  current_velocity: number; rolling_avg_velocity: number
  variance_pct: number; acknowledged: boolean
}

interface ManualSaleRow {
  id: number; product: number; m_number: string; quantity: number
  sale_date: string; channel: string; notes: string
  entered_by_username: string | null; created_at: string
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-GB', { hour12: false })
}

function fmtNum(n: number): string {
  return n.toLocaleString('en-GB')
}

const STATUS_STYLES: Record<string, string> = {
  OUT_OF_STOCK: 'bg-red-100 text-red-800 border-red-300',
  LOW:          'bg-amber-100 text-amber-800 border-amber-300',
  OK:           'bg-green-100 text-green-800 border-green-300',
  SURPLUS:      'bg-blue-100 text-blue-800 border-blue-300',
}

const STATUS_LABELS: Record<string, string> = {
  OUT_OF_STOCK: 'Out of stock',
  LOW:          'Low',
  OK:           'OK',
  SURPLUS:      'Surplus',
}

// ─── Main ──────────────────────────────────────────────────────────────────

export default function SalesVelocityPage() {
  const [summary, setSummary] = useState<SummaryPayload | null>(null)
  const [rows, setRows] = useState<TableRow[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [snapshotDate, setSnapshotDate] = useState<string | null>(null)
  const [unmatched, setUnmatched] = useState<UnmatchedRow[]>([])
  const [driftAlerts, setDriftAlerts] = useState<DriftAlertRow[]>([])
  const [manualSales, setManualSales] = useState<ManualSaleRow[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshBusy, setRefreshBusy] = useState(false)

  // Filters
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [sortBy, setSortBy] = useState('deficit')

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (search) params.set('search', search)
      if (statusFilter) params.set('status', statusFilter)
      if (sortBy) params.set('sort', sortBy)
      params.set('limit', '300')

      const [s, t, u, d, ms] = await Promise.all([
        api('/api/sales-velocity/summary/').then(r => r.json()),
        api(`/api/sales-velocity/table/?${params}`).then(r => r.json()),
        api('/api/sales-velocity/unmatched/').then(r => r.json()),
        api('/api/sales-velocity/drift-alerts/').then(r => r.json()),
        api('/api/sales-velocity/manual-sales/').then(r => r.json()),
      ])
      setSummary(s)
      setRows(t.rows ?? [])
      setTotalCount(t.total_count ?? 0)
      setSnapshotDate(t.snapshot_date)
      setUnmatched(u.results ?? u)
      setDriftAlerts(d.results ?? d)
      setManualSales(ms.results ?? ms)
    } catch (e) {
      console.error('Failed to load sales velocity data', e)
    } finally {
      setLoading(false)
    }
  }, [search, statusFilter, sortBy])

  useEffect(() => { loadAll() }, [loadAll])

  const handleRefresh = async () => {
    setRefreshBusy(true)
    try {
      await api('/api/sales-velocity/refresh/', { method: 'POST' })
      setTimeout(() => { loadAll(); setRefreshBusy(false) }, 3000)
    } catch {
      setRefreshBusy(false)
    }
  }

  if (loading && !summary) {
    return <div className="p-6 text-gray-500">Loading Sales Velocity…</div>
  }

  return (
    <div className="p-4 space-y-4 max-w-[1600px] mx-auto">
      {/* ── Tier 2: Summary header ── */}
      {summary && <SummaryHeader summary={summary} onRefresh={handleRefresh} refreshBusy={refreshBusy} />}

      {/* ── Action panels (drift / unmatched) — collapsible ── */}
      {driftAlerts.length > 0 && <DriftAlertPanel alerts={driftAlerts} onChange={loadAll} />}
      {unmatched.length > 0 && <UnmatchedPanel rows={unmatched} onChange={loadAll} />}

      {/* ── Tier 1: Ivan-parity table ── */}
      <TableControls
        search={search} setSearch={setSearch}
        statusFilter={statusFilter} setStatusFilter={setStatusFilter}
        sortBy={sortBy} setSortBy={setSortBy}
        totalCount={totalCount} shownCount={rows.length}
        snapshotDate={snapshotDate}
      />
      <VelocityTable rows={rows} />

      {/* ── Footfall entry ── */}
      <FootfallForm existing={manualSales} onChange={loadAll} />
    </div>
  )
}

// ─── Tier 2: Summary header ────────────────────────────────────────────────

function SummaryHeader({
  summary, onRefresh, refreshBusy,
}: { summary: SummaryPayload; onRefresh: () => void; refreshBusy: boolean }) {
  return (
    <div className="rounded-lg border p-4 space-y-3" style={{ borderLeftColor: '#674ea7', borderLeftWidth: 4 }}>
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold" style={{ color: '#674ea7' }}>
          Sales Velocity
        </h1>
        <div className="flex items-center gap-3">
          {summary.shadow_mode_enabled && (
            <span className="px-2 py-1 bg-amber-100 text-amber-800 text-xs font-semibold rounded border border-amber-300">
              SHADOW MODE
            </span>
          )}
          {!summary.shadow_mode_enabled && (
            <span className="px-2 py-1 bg-green-100 text-green-800 text-xs font-semibold rounded border border-green-300">
              LIVE
            </span>
          )}
          <button
            onClick={onRefresh}
            disabled={refreshBusy}
            className="px-3 py-1.5 text-sm bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
          >
            {refreshBusy ? 'Refreshing…' : 'Refresh now'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 text-sm">
        <StatCard label="Units on hand" value={fmtNum(summary.total_units_on_hand)} />
        <StatCard label="60-day target" value={fmtNum(summary.total_sixty_day_target)} />
        <StatCard
          label="Coverage"
          value={`${summary.coverage_pct}%`}
          colour={summary.coverage_pct >= 95 ? 'text-green-700' : summary.coverage_pct >= 80 ? 'text-amber-700' : 'text-red-700'}
        />
        <StatCard label="Need making" value={String(summary.products_need_making)} colour="text-amber-700" />
        <StatCard label="Out of stock" value={String(summary.out_of_stock_count)} colour="text-red-700" />
        <StatCard label="Surplus" value={String(summary.surplus_count)} colour="text-blue-700" />
      </div>

      <div className="text-xs text-gray-500">
        Last sync: {fmtDate(summary.last_sync_at)}
        {summary.latest_snapshot_date && <> · Snapshot: {summary.latest_snapshot_date}</>}
      </div>
    </div>
  )
}

function StatCard({ label, value, colour }: { label: string; value: string; colour?: string }) {
  return (
    <div className="bg-gray-50 rounded p-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-bold ${colour || 'text-gray-900'}`}>{value}</div>
    </div>
  )
}

// ─── Tier 1: Table controls ────────────────────────────────────────────────

function TableControls({
  search, setSearch, statusFilter, setStatusFilter, sortBy, setSortBy,
  totalCount, shownCount, snapshotDate,
}: {
  search: string; setSearch: (s: string) => void
  statusFilter: string; setStatusFilter: (s: string) => void
  sortBy: string; setSortBy: (s: string) => void
  totalCount: number; shownCount: number; snapshotDate: string | null
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <input
        type="text"
        placeholder="Search M-number or description…"
        value={search}
        onChange={e => setSearch(e.target.value)}
        className="border rounded px-2 py-1 w-60"
      />
      <select
        value={statusFilter}
        onChange={e => setStatusFilter(e.target.value)}
        className="border rounded px-2 py-1"
      >
        <option value="">All statuses</option>
        <option value="OUT_OF_STOCK">Out of stock</option>
        <option value="LOW">Low</option>
        <option value="OK">OK</option>
        <option value="SURPLUS">Surplus</option>
      </select>
      <select
        value={sortBy}
        onChange={e => setSortBy(e.target.value)}
        className="border rounded px-2 py-1"
      >
        <option value="deficit">Sort by deficit</option>
        <option value="velocity">Sort by velocity</option>
        <option value="m_number">Sort by M-number</option>
      </select>
      <span className="text-gray-500 ml-auto">
        {shownCount} of {totalCount} products
        {snapshotDate && <> · data from {snapshotDate}</>}
      </span>
    </div>
  )
}

// ─── Tier 1: Ivan-parity velocity table ────────────────────────────────────

function VelocityTable({ rows }: { rows: TableRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="text-gray-500 italic p-4">
        No velocity data yet — run <code>refresh_sales_velocity</code> or wait
        for the 04:17 UTC daily schedule.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto border rounded">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-left text-gray-600 text-xs sticky top-0">
          <tr>
            <th className="px-2 py-1.5">M#</th>
            <th className="px-2 py-1.5">Description</th>
            <th className="px-2 py-1.5">Blank</th>
            <th className="px-2 py-1.5">Material</th>
            <th className="px-2 py-1.5 text-right">Stock</th>
            <th className="px-2 py-1.5 text-right">Deficit</th>
            <th className="px-2 py-1.5 text-right">60D Target</th>
            <th className="px-2 py-1.5">Status</th>
            <th className="px-2 py-1.5 text-right">30D Sales</th>
            <th className="px-2 py-1.5 text-right">60D Est.</th>
            <th className="px-2 py-1.5">Channels</th>
            <th className="px-2 py-1.5 text-right">WIP</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.product_id} className="border-t hover:bg-gray-50">
              <td className="px-2 py-1 font-mono text-xs font-bold whitespace-nowrap">{r.m_number}</td>
              <td className="px-2 py-1 truncate max-w-[220px]" title={r.description}>{r.description}</td>
              <td className="px-2 py-1 text-xs text-gray-600 whitespace-nowrap">{r.blank}</td>
              <td className="px-2 py-1 text-xs text-gray-600 whitespace-nowrap truncate max-w-[100px]" title={r.material}>{r.material}</td>
              <td className="px-2 py-1 text-right tabular-nums">{r.current_stock}</td>
              <td className={`px-2 py-1 text-right tabular-nums font-bold ${
                r.deficit > 0 ? 'text-red-700' : r.deficit < -20 ? 'text-blue-600' : 'text-green-700'
              }`}>
                {r.deficit > 0 ? `+${r.deficit}` : r.deficit}
              </td>
              <td className="px-2 py-1 text-right tabular-nums text-gray-600">{r.sixty_day_target}</td>
              <td className="px-2 py-1">
                <span className={`inline-block px-1.5 py-0.5 text-xs rounded border ${STATUS_STYLES[r.status] || ''}`}>
                  {STATUS_LABELS[r.status] || r.status}
                </span>
              </td>
              <td className="px-2 py-1 text-right tabular-nums font-bold">{r.velocity_30d || ''}</td>
              <td className="px-2 py-1 text-right tabular-nums text-gray-600">{r.velocity_60d_est || ''}</td>
              <td className="px-2 py-1 text-xs text-gray-500 whitespace-nowrap truncate max-w-[180px]" title={r.channels}>
                {r.channels || '—'}
              </td>
              <td className="px-2 py-1 text-right">
                {r.wip_count > 0 && (
                  <span className="inline-block px-1.5 py-0.5 text-xs bg-amber-100 text-amber-800 rounded">
                    {r.wip_count}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Action panels ─────────────────────────────────────────────────────────

function DriftAlertPanel({ alerts, onChange }: { alerts: DriftAlertRow[]; onChange: () => void }) {
  const ack = async (id: number) => {
    await api(`/api/sales-velocity/drift-alerts/${id}/acknowledge/`, { method: 'POST' })
    onChange()
  }
  return (
    <details open className="border-2 border-red-400 rounded p-3 bg-red-50">
      <summary className="font-bold text-red-900 cursor-pointer">
        Drift alerts ({alerts.length})
      </summary>
      <table className="w-full text-sm mt-2">
        <thead className="text-left text-gray-600 text-xs">
          <tr><th>M#</th><th className="text-right">Current</th><th className="text-right">7d avg</th><th className="text-right">Var %</th><th>Detected</th><th></th></tr>
        </thead>
        <tbody>
          {alerts.map(a => (
            <tr key={a.id} className="border-t">
              <td className="font-mono">{a.m_number}</td>
              <td className="text-right">{a.current_velocity}</td>
              <td className="text-right">{a.rolling_avg_velocity}</td>
              <td className="text-right font-bold text-red-700">{a.variance_pct}%</td>
              <td className="text-xs text-gray-500">{fmtDate(a.detected_at)}</td>
              <td><button onClick={() => ack(a.id)} className="px-2 py-0.5 bg-gray-200 hover:bg-gray-300 rounded text-xs">Ack</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

function UnmatchedPanel({ rows, onChange }: { rows: UnmatchedRow[]; onChange: () => void }) {
  const ignore = async (id: number) => {
    await api(`/api/sales-velocity/unmatched/${id}/ignore/`, { method: 'POST' })
    onChange()
  }
  const mapTo = async (id: number) => {
    const pid = prompt('Product ID to resolve to:')
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
    <details className="border rounded p-3">
      <summary className="font-bold cursor-pointer">
        Unmatched SKUs ({rows.length})
      </summary>
      <table className="w-full text-sm mt-2">
        <thead className="text-left text-gray-600 text-xs">
          <tr><th>Channel</th><th>SKU</th><th className="text-right">30d</th><th>First</th><th>Last</th><th></th></tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id} className="border-t">
              <td className="text-xs">{r.channel}</td>
              <td className="font-mono text-xs">{r.external_sku}</td>
              <td className="text-right">{r.units_sold_30d}</td>
              <td className="text-xs text-gray-500">{r.first_seen}</td>
              <td className="text-xs text-gray-500">{r.last_seen}</td>
              <td className="space-x-1">
                <button onClick={() => mapTo(r.id)} className="px-1.5 py-0.5 bg-violet-200 hover:bg-violet-300 rounded text-xs">Map</button>
                <button onClick={() => ignore(r.id)} className="px-1.5 py-0.5 bg-gray-200 hover:bg-gray-300 rounded text-xs">Ignore</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

// ─── Footfall ──────────────────────────────────────────────────────────────

function FootfallForm({ existing, onChange }: { existing: ManualSaleRow[]; onChange: () => void }) {
  const [productId, setProductId] = useState('')
  const [qty, setQty] = useState('')
  const [saleDate, setSaleDate] = useState(new Date().toISOString().slice(0, 10))
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    const r = await api('/api/sales-velocity/manual-sales/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product: Number(productId), quantity: Number(qty), sale_date: saleDate, channel: 'footfall', notes }),
    })
    setBusy(false)
    if (r.ok) { setProductId(''); setQty(''); setNotes(''); onChange() }
    else alert(`Failed: ${r.status}`)
  }

  const del = async (id: number) => {
    if (!confirm('Delete?')) return
    await api(`/api/sales-velocity/manual-sales/${id}/`, { method: 'DELETE' })
    onChange()
  }

  return (
    <details className="border rounded p-3">
      <summary className="font-bold cursor-pointer">Footfall entry</summary>
      <form onSubmit={submit} className="flex flex-wrap gap-2 items-end mt-2 mb-3">
        <label className="text-xs">Product ID<input type="number" value={productId} onChange={e => setProductId(e.target.value)} required className="block border rounded px-2 py-1 w-24" /></label>
        <label className="text-xs">Qty<input type="number" min="1" value={qty} onChange={e => setQty(e.target.value)} required className="block border rounded px-2 py-1 w-16" /></label>
        <label className="text-xs">Date<input type="date" value={saleDate} onChange={e => setSaleDate(e.target.value)} required className="block border rounded px-2 py-1" /></label>
        <label className="text-xs flex-1 min-w-[120px]">Notes<input type="text" value={notes} onChange={e => setNotes(e.target.value)} className="block border rounded px-2 py-1 w-full" /></label>
        <button type="submit" disabled={busy} className="px-3 py-1 bg-violet-600 text-white rounded disabled:opacity-50 text-sm">{busy ? 'Saving…' : 'Add'}</button>
      </form>
      {existing.length > 0 && (
        <table className="w-full text-xs">
          <thead className="text-left text-gray-600"><tr><th>M#</th><th>Qty</th><th>Date</th><th>Notes</th><th>By</th><th></th></tr></thead>
          <tbody>
            {existing.slice(0, 10).map(r => (
              <tr key={r.id} className="border-t">
                <td>{r.m_number}</td><td>{r.quantity}</td><td>{r.sale_date}</td>
                <td className="truncate max-w-[150px]">{r.notes}</td><td>{r.entered_by_username || '—'}</td>
                <td><button onClick={() => del(r.id)} className="text-red-600 hover:text-red-800">x</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  )
}
