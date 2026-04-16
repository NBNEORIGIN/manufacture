'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface MarginRow {
  asin: string
  marketplace: string
  m_number: string | null
  units: number
  gross_revenue: number
  net_revenue: number
  fees_per_unit: number | null
  fees_total: number | null
  cogs_per_unit: number | null
  cogs_total: number | null
  ad_spend: number
  gross_profit: number | null
  gross_margin_pct: number | null
  net_profit: number | null
  net_margin_pct: number | null
  fee_source: string | null
  cost_source: string | null
  is_composite: boolean
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
}

interface Summary {
  total_skus: number
  scored_skus: number
  buckets: { healthy: number; thin: number; unprofitable: number; unknown: number }
  total_net_revenue: number
  total_net_profit: number
}

interface MarginResponse {
  marketplace: string
  lookback_days: number
  summary: Summary
  results: MarginRow[]
}

// ── Constants ─────────────────────────────────────────────────────────────────

const MARKETPLACES = [
  { code: 'UK', label: 'UK' },
  { code: 'DE', label: 'DE' },
  { code: 'FR', label: 'FR' },
  { code: 'IT', label: 'IT' },
  { code: 'ES', label: 'ES' },
  { code: 'US', label: 'US' },
  { code: 'CA', label: 'CA' },
  { code: 'AU', label: 'AU' },
]

const LOOKBACKS = [
  { days: 7, label: '7d' },
  { days: 30, label: '30d' },
  { days: 90, label: '90d' },
]

const CURRENCY: Record<string, string> = {
  UK: 'GBP', DE: 'EUR', FR: 'EUR', IT: 'EUR', ES: 'EUR',
  US: 'USD', CA: 'CAD', AU: 'AUD',
}

type SortKey = keyof MarginRow
type SortDir = 'asc' | 'desc'

// ── Helpers ───────────────────────────────────────────────────────────────────

function money(v: number | null | undefined, mp: string): string {
  if (v === null || v === undefined) return '—'
  const cur = CURRENCY[mp] ?? 'GBP'
  try { return new Intl.NumberFormat('en-GB', { style: 'currency', currency: cur, maximumFractionDigits: 2 }).format(v) }
  catch { return v.toFixed(2) }
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${v.toFixed(1)}%`
}

function cmpVals(a: unknown, b: unknown, dir: SortDir): number {
  const aN = a === null || a === undefined
  const bN = b === null || b === undefined
  if (aN && bN) return 0
  if (aN) return 1
  if (bN) return -1
  if (typeof a === 'number' && typeof b === 'number') return dir === 'asc' ? a - b : b - a
  const sa = String(a).toLowerCase(), sb = String(b).toLowerCase()
  return dir === 'asc' ? sa.localeCompare(sb) : sb.localeCompare(sa)
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ProfitabilityPage() {
  const [mp, setMp] = useState('UK')
  const [lookback, setLookback] = useState(30)
  const [data, setData] = useState<MarginResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const [query, setQuery] = useState('')
  const [onlyLoss, setOnlyLoss] = useState(false)
  const [minConf, setMinConf] = useState<'ANY' | 'MEDIUM' | 'HIGH'>('ANY')
  const [sortKey, setSortKey] = useState<SortKey>('net_profit')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const load = useCallback(async () => {
    setLoading(true); setErr(null)
    try {
      const r = await api(`/api/cairn/margin/per-sku/?marketplace=${mp}&lookback_days=${lookback}`)
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j?.detail || j?.error || `HTTP ${r.status}`) }
      setData(await r.json() as MarginResponse)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e)); setData(null)
    } finally { setLoading(false) }
  }, [mp, lookback])

  useEffect(() => { load() }, [load])

  const columns: { key: SortKey; label: string; right?: boolean; fmt?: (v: unknown) => string }[] = useMemo(() => [
    { key: 'asin', label: 'ASIN' },
    { key: 'm_number', label: 'M#' },
    { key: 'units', label: 'Units', right: true },
    { key: 'net_revenue', label: 'Net rev', right: true, fmt: v => money(v as number, mp) },
    { key: 'fees_total', label: 'Fees', right: true, fmt: v => money(v as number | null, mp) },
    { key: 'cogs_total', label: 'COGS', right: true, fmt: v => money(v as number | null, mp) },
    { key: 'ad_spend', label: 'Ads', right: true, fmt: v => money(v as number, mp) },
    { key: 'net_profit', label: 'Net profit', right: true, fmt: v => money(v as number | null, mp) },
    { key: 'net_margin_pct', label: 'Margin', right: true, fmt: v => pct(v as number | null) },
    { key: 'confidence', label: 'Conf' },
  ], [mp])

  const rows = useMemo(() => {
    if (!data) return []
    const q = query.trim().toLowerCase()
    return data.results
      .filter(r => {
        if (q && !r.asin.toLowerCase().includes(q) && !(r.m_number ?? '').toLowerCase().includes(q)) return false
        if (onlyLoss && (r.net_profit === null || r.net_profit >= 0)) return false
        if (minConf === 'HIGH' && r.confidence !== 'HIGH') return false
        if (minConf === 'MEDIUM' && r.confidence === 'LOW') return false
        return true
      })
      .slice()
      .sort((a, b) => cmpVals((a as Record<string, unknown>)[sortKey], (b as Record<string, unknown>)[sortKey], sortDir))
  }, [data, query, onlyLoss, minConf, sortKey, sortDir])

  function headerClick(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const costWarning = useMemo(() => {
    if (!data) return null
    const scored = data.results.filter(r => r.cogs_per_unit !== null)
    if (scored.length < 10) return null
    const uniq = new Set(scored.map(r => r.cogs_per_unit))
    if (uniq.size === 1) {
      const v = Array.from(uniq)[0]
      return `All ${scored.length} SKUs show identical COGS (${money(v, mp)}/unit). Blank costs haven\u2019t been populated \u2014 profit figures are placeholders until they are.`
    }
    return null
  }, [data, mp])

  const s = data?.summary
  const b = s?.buckets

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold">Profitability</h1>
          <p className="text-sm text-gray-500">Per-SKU margin from orders, fees, COGS and ads. Click any column header to sort.</p>
        </div>
        <button onClick={load} className="text-sm px-3 py-1.5 border rounded hover:bg-gray-50">Refresh</button>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4 bg-white border rounded-lg p-3 text-sm">
        <label className="flex items-center gap-1.5 text-xs text-gray-600">
          Marketplace
          <select value={mp} onChange={e => setMp(e.target.value)} className="border rounded px-2 py-1 text-sm bg-white">
            {MARKETPLACES.map(m => <option key={m.code} value={m.code}>{m.label}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-gray-600">
          Lookback
          <select value={lookback} onChange={e => setLookback(Number(e.target.value))} className="border rounded px-2 py-1 text-sm bg-white">
            {LOOKBACKS.map(c => <option key={c.days} value={c.days}>{c.label}</option>)}
          </select>
        </label>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter ASIN or M#\u2026" className="flex-1 min-w-[140px] border rounded px-2 py-1 text-sm" />
        <label className="flex items-center gap-1 text-xs text-gray-600">
          <input type="checkbox" checked={onlyLoss} onChange={e => setOnlyLoss(e.target.checked)} /> Loss-makers only
        </label>
        <label className="flex items-center gap-1.5 text-xs text-gray-600">
          Confidence
          <select value={minConf} onChange={e => setMinConf(e.target.value as typeof minConf)} className="border rounded px-2 py-1 text-sm bg-white">
            <option value="ANY">Any</option>
            <option value="MEDIUM">Medium+</option>
            <option value="HIGH">High only</option>
          </select>
        </label>
      </div>

      {costWarning && (
        <div className="mb-4 border border-amber-300 bg-amber-50 rounded-lg p-3 text-sm text-amber-900">
          <span className="font-medium">Cost data incomplete: </span>{costWarning}
        </div>
      )}

      {err && <div className="mb-4 border border-red-300 bg-red-50 rounded-lg p-3 text-sm text-red-900">{err}</div>}

      {/* Summary cards */}
      {s && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-4">
          <Card label="Net revenue" value={money(s.total_net_revenue, mp)} />
          <Card label="Net profit" value={money(s.total_net_profit, mp)} cls={s.total_net_profit >= 0 ? 'text-green-700' : 'text-red-700'} />
          <Card label="Healthy (\u226520%)" value={String(b?.healthy ?? 0)} cls="text-green-700" />
          <Card label="Thin (5\u201320%)" value={String(b?.thin ?? 0)} cls="text-amber-600" />
          <Card label="Unprofitable" value={String(b?.unprofitable ?? 0)} cls="text-red-700" />
          <Card label="Unknown" value={String(b?.unknown ?? 0)} cls="text-gray-400" />
        </div>
      )}

      {/* Table */}
      <div className="bg-white border rounded-lg overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
            <tr>
              {columns.map(c => (
                <th key={c.key as string} onClick={() => headerClick(c.key)}
                  className={`px-3 py-2 cursor-pointer select-none whitespace-nowrap hover:bg-gray-100 ${c.right ? 'text-right' : 'text-left'}`}>
                  {c.label}
                  {sortKey === c.key && <span className="ml-1 text-gray-400">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && <tr><td colSpan={columns.length} className="p-6 text-center text-gray-400">Loading\u2026</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={columns.length} className="p-6 text-center text-gray-400">No rows.</td></tr>}
            {!loading && rows.map(r => (
              <tr key={`${r.asin}-${r.marketplace}`} className={`hover:bg-gray-50 ${r.confidence === 'LOW' ? 'text-gray-400' : ''}`}>
                {columns.map(c => {
                  const raw = (r as Record<string, unknown>)[c.key]
                  let cell: React.ReactNode
                  if (c.key === 'confidence') {
                    const map = { HIGH: 'bg-green-100 text-green-700', MEDIUM: 'bg-amber-100 text-amber-700', LOW: 'bg-red-100 text-red-700' }
                    const short = { HIGH: 'HIGH', MEDIUM: 'MED', LOW: 'LOW' }
                    cell = <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${map[r.confidence]}`}>{short[r.confidence]}</span>
                  } else if (c.key === 'net_margin_pct') {
                    const cls = r.net_margin_pct === null ? 'text-gray-400' : r.net_margin_pct >= 20 ? 'text-green-700 font-medium' : r.net_margin_pct >= 5 ? 'text-amber-600' : 'text-red-700 font-medium'
                    cell = <span className={cls}>{pct(r.net_margin_pct)}</span>
                  } else if (c.key === 'net_profit') {
                    const cls = r.net_profit === null ? 'text-gray-400' : r.net_profit >= 0 ? 'text-green-700' : 'text-red-700'
                    cell = <span className={cls}>{money(r.net_profit, mp)}</span>
                  } else if (c.fmt) {
                    cell = c.fmt(raw)
                  } else {
                    cell = raw === null || raw === undefined ? '—' : String(raw)
                  }
                  return <td key={c.key as string} className={`px-3 py-2 whitespace-nowrap ${c.right ? 'text-right' : 'text-left'}`}>{cell}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && (
        <p className="mt-3 text-xs text-gray-500">
          Showing <b>{rows.length}</b> of <b>{data.summary.total_skus}</b> SKUs
          {' \u00b7 '}{data.marketplace} {' \u00b7 '} last {data.lookback_days} days
        </p>
      )}
    </div>
  )
}

function Card({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="bg-white border rounded-lg p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-semibold mt-0.5 ${cls ?? 'text-gray-900'}`}>{value}</div>
    </div>
  )
}
