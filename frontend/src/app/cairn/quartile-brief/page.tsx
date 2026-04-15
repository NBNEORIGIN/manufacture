'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/api'

// ─── Types (mirror core/amazon_intel/margin/quartile_brief.py) ─────────────

type Action = 'PAUSE' | 'REDUCE' | 'INCREASE' | 'HOLD'

interface Recommendation {
  asin: string
  sku: string | null
  m_number: string | null
  account_name: string
  country_code: string
  action: Action
  reason: string
  caveats: string[]
  spend: number
  ad_sales: number
  total_revenue: number
  units: number
  current_acos: number | null
  current_tacos: number | null
  organic_rate: number | null
  recommended_acos: number | null
}

interface BriefBasis {
  lookback_days: number
  target_margin_pct: number
  non_ad_cost_pct: number
  max_tacos: number
}

interface BriefSummary {
  total_skus_with_spend: number
  counts: Record<Action, number>
}

interface Brief {
  marketplace: string
  generated_at: string
  basis: BriefBasis
  summary: BriefSummary
  recommendations: Recommendation[]
}

// ─── Helpers ───────────────────────────────────────────────────────────────

const MARKETPLACES = ['UK', 'DE', 'FR', 'ES', 'IT', 'NL', 'US', 'CA', 'AU'] as const

function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function fmtMoney(v: number | null | undefined, currency = '£'): string {
  if (v === null || v === undefined) return '—'
  return `${currency}${v.toFixed(2)}`
}

function actionBadge(action: Action): string {
  switch (action) {
    case 'PAUSE':
      return 'bg-red-100 text-red-800 border-red-200'
    case 'REDUCE':
      return 'bg-orange-100 text-orange-800 border-orange-200'
    case 'INCREASE':
      return 'bg-green-100 text-green-800 border-green-200'
    case 'HOLD':
      return 'bg-gray-100 text-gray-700 border-gray-200'
  }
}

// Shared button classes so Refresh/Copy/Download/Force-sync share one size.
const BTN_BASE =
  'text-sm px-3 py-1.5 rounded border h-9 inline-flex items-center justify-center whitespace-nowrap min-w-[112px]'
const BTN_PRIMARY =
  `${BTN_BASE} bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white border-blue-600`
const BTN_SECONDARY =
  `${BTN_BASE} bg-gray-100 hover:bg-gray-200 disabled:bg-gray-50 disabled:text-gray-400 text-gray-800 border-gray-300`

// ─── Column definitions for sort/filter ────────────────────────────────────

type SortDir = 'asc' | 'desc'
type ColumnKey =
  | 'm_number' | 'sku' | 'asin' | 'account'
  | 'spend' | 'ad_sales' | 'total_revenue' | 'units'
  | 'current_acos' | 'recommended_acos' | 'organic_rate' | 'reason'

interface ColumnDef {
  key: ColumnKey
  label: string
  align: 'left' | 'right'
  kind: 'text' | 'num'
  get: (r: Recommendation) => string | number | null
}

const COLUMNS: ColumnDef[] = [
  { key: 'm_number',        label: 'M#',          align: 'left',  kind: 'text', get: (r) => r.m_number ?? '' },
  { key: 'sku',             label: 'SKU',         align: 'left',  kind: 'text', get: (r) => r.sku ?? '' },
  { key: 'asin',            label: 'ASIN',        align: 'left',  kind: 'text', get: (r) => r.asin },
  { key: 'account',         label: 'Account',     align: 'left',  kind: 'text', get: (r) => `${r.country_code} / ${r.account_name}` },
  { key: 'spend',           label: 'Spend',       align: 'right', kind: 'num',  get: (r) => r.spend },
  { key: 'ad_sales',        label: 'Ad sales',    align: 'right', kind: 'num',  get: (r) => r.ad_sales },
  { key: 'total_revenue',   label: 'Revenue',     align: 'right', kind: 'num',  get: (r) => r.total_revenue },
  { key: 'units',           label: 'Units',       align: 'right', kind: 'num',  get: (r) => r.units },
  { key: 'current_acos',    label: 'ACOS',        align: 'right', kind: 'num',  get: (r) => r.current_acos },
  { key: 'recommended_acos', label: 'Recommended', align: 'right', kind: 'num', get: (r) => r.recommended_acos },
  { key: 'organic_rate',    label: 'Organic',     align: 'right', kind: 'num',  get: (r) => r.organic_rate },
  { key: 'reason',          label: 'Reason / Caveats', align: 'left', kind: 'text', get: (r) => r.reason + ' ' + r.caveats.join(' ') },
]

function applyFilterSort(
  rows: Recommendation[],
  filters: Record<string, string>,
  sort: { key: ColumnKey; dir: SortDir } | null,
): Recommendation[] {
  // Filter: case-insensitive substring on the column's formatted value.
  let out = rows
  const active = Object.entries(filters).filter(([, v]) => v.trim() !== '')
  if (active.length > 0) {
    out = out.filter((r) =>
      active.every(([k, v]) => {
        const col = COLUMNS.find((c) => c.key === k)
        if (!col) return true
        const val = col.get(r)
        const s = val === null || val === undefined ? '' : String(val)
        return s.toLowerCase().includes(v.toLowerCase())
      })
    )
  }
  if (sort) {
    const col = COLUMNS.find((c) => c.key === sort.key)
    if (col) {
      const mul = sort.dir === 'asc' ? 1 : -1
      out = [...out].sort((a, b) => {
        const av = col.get(a)
        const bv = col.get(b)
        if (av === null || av === undefined || av === '') return 1
        if (bv === null || bv === undefined || bv === '') return -1
        if (col.kind === 'num') return (Number(av) - Number(bv)) * mul
        return String(av).localeCompare(String(bv)) * mul
      })
    }
  }
  return out
}

function recsToCsv(rows: Recommendation[], brief: Brief): string {
  const esc = (v: unknown): string => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines: string[] = []
  lines.push(
    `# Quartile ACOS Brief — ${brief.marketplace} — generated ${brief.generated_at} — filtered export (${rows.length} of ${brief.recommendations.length} SKUs)`,
  )
  lines.push(
    `# Basis: lookback ${brief.basis.lookback_days} days,` +
      ` target margin ${(brief.basis.target_margin_pct * 100).toFixed(1)}%,` +
      ` max TACOS ${(brief.basis.max_tacos * 100).toFixed(1)}%`,
  )
  lines.push('')
  lines.push(
    [
      'action', 'm_number', 'sku', 'asin', 'account_name', 'country_code',
      'spend', 'ad_sales', 'total_revenue', 'units',
      'current_acos', 'recommended_acos', 'organic_rate',
      'reason', 'caveats',
    ].join(','),
  )
  for (const r of rows) {
    lines.push(
      [
        r.action,
        r.m_number ?? '',
        r.sku ?? '',
        r.asin,
        r.account_name,
        r.country_code,
        r.spend.toFixed(2),
        r.ad_sales.toFixed(2),
        r.total_revenue.toFixed(2),
        r.units,
        r.current_acos === null ? '' : r.current_acos.toFixed(4),
        r.recommended_acos === null ? '' : r.recommended_acos.toFixed(4),
        r.organic_rate === null ? '' : r.organic_rate.toFixed(4),
        r.reason,
        (r.caveats ?? []).join(' | '),
      ].map(esc).join(','),
    )
  }
  return lines.join('\n')
}

// ─── Component ─────────────────────────────────────────────────────────────

export default function QuartileBriefPage() {
  const [marketplace, setMarketplace] = useState<string>('UK')
  const [lookbackDays, setLookbackDays] = useState<number>(30)
  const [targetMarginPct, setTargetMarginPct] = useState<number>(0.06)
  const [nonAdCostPct, setNonAdCostPct] = useState<number>(0.82)
  const [brief, setBrief] = useState<Brief | null>(null)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<boolean>(false)
  const [syncing, setSyncing] = useState<boolean>(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)

  // Per-table sort/filter state, keyed by action bucket so PAUSE/REDUCE/etc.
  // each retain their own view.
  const [sortState, setSortState] = useState<Record<Action, { key: ColumnKey; dir: SortDir } | null>>({
    PAUSE: null, REDUCE: null, INCREASE: null, HOLD: null,
  })
  const [filterState, setFilterState] = useState<Record<Action, Record<string, string>>>({
    PAUSE: {}, REDUCE: {}, INCREASE: {}, HOLD: {},
  })

  const fetchBrief = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        marketplace,
        lookback_days: String(lookbackDays),
        target_margin_pct: String(targetMarginPct),
        non_ad_cost_pct: String(nonAdCostPct),
      })
      const r = await api(`/api/cairn/quartile-brief/?${params}`)
      if (!r.ok) {
        let msg = `HTTP ${r.status}`
        try {
          const body = await r.json()
          if (body?.detail) msg += ` — ${body.detail}`
          else if (body?.error) msg += ` — ${body.error}`
        } catch {
          const t = await r.text()
          if (t) msg += ` — ${t.slice(0, 200)}`
        }
        throw new Error(msg)
      }
      const data: Brief = await r.json()
      setBrief(data)
    } catch (e: any) {
      setError(e?.message || 'Unknown error')
      setBrief(null)
    } finally {
      setLoading(false)
    }
  }, [marketplace, lookbackDays, targetMarginPct, nonAdCostPct])

  useEffect(() => { fetchBrief() }, [fetchBrief])

  const copyAsEmail = useCallback(async () => {
    const params = new URLSearchParams({
      marketplace,
      lookback_days: String(lookbackDays),
      target_margin_pct: String(targetMarginPct),
      non_ad_cost_pct: String(nonAdCostPct),
      format: 'text',
    })
    try {
      const r = await api(`/api/cairn/quartile-brief/?${params}`)
      const text = await r.text()
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch (e: any) {
      setError(`Copy failed: ${e?.message || e}`)
    }
  }, [marketplace, lookbackDays, targetMarginPct, nonAdCostPct])

  const triggerSync = useCallback(async () => {
    if (!confirm('Trigger a fresh ads data sync? This runs in the background on Cairn and typically takes 15–30 minutes to complete across all regions.')) return
    setSyncing(true)
    setSyncMsg(null)
    try {
      const r = await api('/api/cairn/ads-sync/', { method: 'POST' })
      if (!r.ok) {
        let msg = `HTTP ${r.status}`
        try {
          const body = await r.json()
          if (body?.detail) msg += ` — ${body.detail}`
        } catch { /* empty */ }
        throw new Error(msg)
      }
      setSyncMsg('Sync started — refresh the brief in 15–30 minutes once the data lands.')
    } catch (e: any) {
      setSyncMsg(`Sync failed: ${e?.message || e}`)
    } finally {
      setSyncing(false)
    }
  }, [])

  const recs = brief?.recommendations ?? []
  const grouped = useMemo(() => {
    const out: Record<Action, Recommendation[]> = {
      PAUSE: [], REDUCE: [], INCREASE: [], HOLD: [],
    }
    for (const r of recs) out[r.action].push(r)
    return out
  }, [recs])

  // Visible rows per bucket (with filter + sort applied) — used for both
  // rendering AND the filtered CSV export.
  const visible = useMemo(() => {
    const out: Record<Action, Recommendation[]> = {
      PAUSE: applyFilterSort(grouped.PAUSE, filterState.PAUSE, sortState.PAUSE),
      REDUCE: applyFilterSort(grouped.REDUCE, filterState.REDUCE, sortState.REDUCE),
      INCREASE: applyFilterSort(grouped.INCREASE, filterState.INCREASE, sortState.INCREASE),
      HOLD: applyFilterSort(grouped.HOLD, filterState.HOLD, sortState.HOLD),
    }
    return out
  }, [grouped, filterState, sortState])

  const downloadCsv = useCallback(() => {
    if (!brief) return
    // Build CSV from the *currently visible* rows across all buckets so
    // Quartile receives exactly the subset the operator has filtered to.
    const combined = [...visible.PAUSE, ...visible.REDUCE, ...visible.INCREASE, ...visible.HOLD]
    const csv = recsToCsv(combined, brief)
    const mkt = brief.marketplace || 'all'
    const today = new Date().toISOString().slice(0, 10)
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `quartile-brief-${mkt}-${today}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, [brief, visible])

  const toggleSort = (action: Action, key: ColumnKey) => {
    setSortState((prev) => {
      const cur = prev[action]
      let next: { key: ColumnKey; dir: SortDir } | null
      if (!cur || cur.key !== key) next = { key, dir: 'asc' }
      else if (cur.dir === 'asc') next = { key, dir: 'desc' }
      else next = null
      return { ...prev, [action]: next }
    })
  }

  const setFilter = (action: Action, key: ColumnKey, value: string) => {
    setFilterState((prev) => ({
      ...prev,
      [action]: { ...prev[action], [key]: value },
    }))
  }

  const totalVisible =
    visible.PAUSE.length + visible.REDUCE.length + visible.INCREASE.length + visible.HOLD.length
  const totalAll = recs.length
  const isFiltered = totalVisible !== totalAll

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Quartile ACOS Brief</h1>
        <p className="text-sm text-gray-600 mt-1">
          Per-SKU ACOS recommendations for Quartile. Account-level v0 assumptions —
          per-SKU margin refinement lands once the cost-price + fee engines ship.
        </p>
      </header>

      {/* Controls */}
      <section className="bg-white border border-gray-200 rounded-md p-4 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Marketplace</label>
            <select
              value={marketplace}
              onChange={(e) => setMarketplace(e.target.value)}
              className="w-full border border-gray-300 rounded px-2 h-9 text-sm"
            >
              {MARKETPLACES.map((m) => <option key={m} value={m}>{m}</option>)}
              <option value="">All</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Lookback (days)</label>
            <input
              type="number" min={1} max={90}
              value={lookbackDays}
              onChange={(e) => setLookbackDays(Number(e.target.value) || 30)}
              className="w-full border border-gray-300 rounded px-2 h-9 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Target margin %</label>
            <input
              type="number" min={0} max={50} step="0.5"
              value={targetMarginPct * 100}
              onChange={(e) => setTargetMarginPct((Number(e.target.value) || 0) / 100)}
              className="w-full border border-gray-300 rounded px-2 h-9 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Non-ad cost %</label>
            <input
              type="number" min={0} max={100} step="1"
              value={nonAdCostPct * 100}
              onChange={(e) => setNonAdCostPct((Number(e.target.value) || 0) / 100)}
              className="w-full border border-gray-300 rounded px-2 h-9 text-sm"
            />
          </div>
          <div className="flex items-end flex-wrap gap-2">
            <button onClick={fetchBrief} disabled={loading} className={BTN_PRIMARY}>
              {loading ? 'Loading…' : 'Refresh'}
            </button>
            <button
              onClick={copyAsEmail}
              disabled={loading || !brief}
              className={BTN_SECONDARY}
              title="Copy email-ready text to clipboard"
            >
              {copied ? 'Copied ✓' : 'Copy as email'}
            </button>
            <button
              onClick={downloadCsv}
              disabled={loading || !brief || totalVisible === 0}
              className={BTN_SECONDARY}
              title={
                isFiltered
                  ? `Download ${totalVisible} filtered rows as CSV`
                  : 'Download all visible rows as CSV'
              }
            >
              {isFiltered ? `CSV (${totalVisible})` : 'Download CSV'}
            </button>
            <button
              onClick={triggerSync}
              disabled={syncing}
              className={BTN_SECONDARY}
              title="Trigger a fresh ads data pull on Cairn (15–30 min to complete)"
            >
              {syncing ? 'Starting…' : 'Force sync'}
            </button>
          </div>
        </div>

        {brief && (
          <div className="text-xs text-gray-500">
            Basis: {brief.basis.lookback_days}-day window, target margin{' '}
            {fmtPct(brief.basis.target_margin_pct, 1)}, max TACOS{' '}
            {fmtPct(brief.basis.max_tacos, 1)}. Generated {new Date(brief.generated_at).toLocaleString('en-GB', { hour12: false })}.
            {isFiltered && (
              <span className="ml-2 text-blue-700">
                Showing {totalVisible} of {totalAll} (filtered).
              </span>
            )}
          </div>
        )}
        {syncMsg && (
          <div className="text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded px-3 py-2">
            {syncMsg}
          </div>
        )}
      </section>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      {/* Summary cards */}
      {brief && (
        <section className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <SummaryCard label="SKUs reviewed" value={brief.summary.total_skus_with_spend} colour="bg-gray-50" />
          <SummaryCard label="Pause" value={brief.summary.counts.PAUSE ?? 0} colour="bg-red-50" />
          <SummaryCard label="Reduce" value={brief.summary.counts.REDUCE ?? 0} colour="bg-orange-50" />
          <SummaryCard label="Increase" value={brief.summary.counts.INCREASE ?? 0} colour="bg-green-50" />
          <SummaryCard label="Hold" value={brief.summary.counts.HOLD ?? 0} colour="bg-gray-50" />
        </section>
      )}

      {/* Recommendations */}
      {brief && (
        <section className="space-y-4">
          {(['PAUSE', 'REDUCE', 'INCREASE', 'HOLD'] as Action[]).map((action) => {
            const allRows = grouped[action]
            const rows = visible[action]
            if (allRows.length === 0) return null
            const sort = sortState[action]
            const filters = filterState[action]
            return (
              <div key={action} className="bg-white border border-gray-200 rounded-md">
                <header className="px-4 py-2 border-b border-gray-200 flex items-center gap-2">
                  <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded border ${actionBadge(action)}`}>
                    {action}
                  </span>
                  <span className="text-sm text-gray-600">
                    {rows.length === allRows.length
                      ? `${allRows.length} SKU${allRows.length === 1 ? '' : 's'}`
                      : `${rows.length} of ${allRows.length} SKU${allRows.length === 1 ? '' : 's'} (filtered)`}
                  </span>
                </header>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 text-xs text-gray-600">
                      <tr>
                        {COLUMNS.map((col) => {
                          const isSorted = sort?.key === col.key
                          const arrow = isSorted ? (sort!.dir === 'asc' ? ' ▲' : ' ▼') : ''
                          return (
                            <th
                              key={col.key}
                              className={`${col.align === 'right' ? 'text-right' : 'text-left'} px-3 py-2 select-none`}
                            >
                              <button
                                onClick={() => toggleSort(action, col.key)}
                                className="font-semibold hover:text-gray-900 inline-flex items-center gap-1"
                                title="Click to sort"
                              >
                                <span>{col.label}</span>
                                <span className="text-gray-400">{arrow || '⇅'}</span>
                              </button>
                            </th>
                          )
                        })}
                      </tr>
                      <tr>
                        {COLUMNS.map((col) => (
                          <th key={`${col.key}-f`} className="px-2 pb-2">
                            <input
                              type="text"
                              placeholder="filter…"
                              value={filters[col.key] ?? ''}
                              onChange={(e) => setFilter(action, col.key, e.target.value)}
                              className="w-full border border-gray-200 rounded px-1.5 py-1 text-xs font-normal"
                            />
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr
                          key={`${r.asin}-${r.country_code}-${r.account_name}-${i}`}
                          className={`border-t border-gray-100 ${i % 2 === 1 ? 'bg-gray-50' : 'bg-white'} hover:bg-blue-50`}
                        >
                          <td className="px-3 py-2 font-mono text-xs">{r.m_number ?? '—'}</td>
                          <td className="px-3 py-2 font-mono text-xs">{r.sku ?? '—'}</td>
                          <td className="px-3 py-2 font-mono text-xs">{r.asin}</td>
                          <td className="px-3 py-2 text-xs">
                            {r.country_code} / {r.account_name}
                          </td>
                          <td className="px-3 py-2 text-right">{fmtMoney(r.spend)}</td>
                          <td className="px-3 py-2 text-right">{fmtMoney(r.ad_sales)}</td>
                          <td className="px-3 py-2 text-right">{fmtMoney(r.total_revenue)}</td>
                          <td className="px-3 py-2 text-right">{r.units}</td>
                          <td className="px-3 py-2 text-right">{fmtPct(r.current_acos)}</td>
                          <td className="px-3 py-2 text-right font-medium">{fmtPct(r.recommended_acos)}</td>
                          <td className="px-3 py-2 text-right">{fmtPct(r.organic_rate)}</td>
                          <td className="px-3 py-2 text-xs text-gray-600 max-w-md">
                            <div>{r.reason}</div>
                            {r.caveats.length > 0 && (
                              <div className="text-amber-700 mt-1">{r.caveats.join(' · ')}</div>
                            )}
                          </td>
                        </tr>
                      ))}
                      {rows.length === 0 && (
                        <tr>
                          <td colSpan={COLUMNS.length} className="px-3 py-4 text-center text-xs text-gray-500">
                            No rows match the current filters.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          })}

          {recs.length === 0 && !loading && (
            <div className="bg-white border border-gray-200 rounded-md p-6 text-center text-sm text-gray-500">
              No SKUs with meaningful ad spend in this window.
              {brief.marketplace && (
                <> Data flows through after the scheduled sync finishes (4×/day on Hetzner).</>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  )
}

function SummaryCard({ label, value, colour }: { label: string; value: number; colour: string }) {
  return (
    <div className={`${colour} rounded-md p-3 border border-gray-200`}>
      <div className="text-xs text-gray-600 uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-bold mt-1">{value}</div>
    </div>
  )
}
