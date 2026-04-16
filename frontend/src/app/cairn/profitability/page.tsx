'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  blank_raw: string | null
  blank_normalized: string | null
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

type SortKey = string
type SortDir = 'asc' | 'desc'

// ── Helpers ───────────────────────────────────────────────────────────────────

function money(v: number | null | undefined, mp: string): string {
  if (v === null || v === undefined) return '\u2014'
  const cur = CURRENCY[mp] ?? 'GBP'
  try { return new Intl.NumberFormat('en-GB', { style: 'currency', currency: cur, maximumFractionDigits: 2 }).format(v) }
  catch { return v.toFixed(2) }
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '\u2014'
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

/** Recalculate derived margin fields when COGS is overridden client-side. */
function recalcRow(r: MarginRow, newCogsPerUnit: number): MarginRow {
  const cogsTotal = newCogsPerUnit * r.units
  const feesTotal = r.fees_total ?? 0
  const grossProfit = r.net_revenue - feesTotal - cogsTotal
  const netProfit = grossProfit - r.ad_spend
  const grossMarginPct = r.net_revenue > 0 ? (grossProfit / r.net_revenue) * 100 : null
  const netMarginPct = r.net_revenue > 0 ? (netProfit / r.net_revenue) * 100 : null
  return {
    ...r,
    cogs_per_unit: newCogsPerUnit,
    cogs_total: Math.round(cogsTotal * 100) / 100,
    gross_profit: Math.round(grossProfit * 100) / 100,
    gross_margin_pct: grossMarginPct !== null ? Math.round(grossMarginPct * 100) / 100 : null,
    net_profit: Math.round(netProfit * 100) / 100,
    net_margin_pct: netMarginPct !== null ? Math.round(netMarginPct * 100) / 100 : null,
  }
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ProfitabilityPage() {
  const [mp, setMp] = useState('UK')
  const [lookback, setLookback] = useState(30)
  const [data, setData] = useState<MarginResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // COGS overrides: keyed by m_number, value = new cogs_per_unit.
  // Applied on top of API data for live recalc.
  const [cogsOverrides, setCogsOverrides] = useState<Record<string, number>>({})
  const [savingCogs, setSavingCogs] = useState<Record<string, boolean>>({})
  const [savedCogs, setSavedCogs] = useState<Record<string, boolean>>({})

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
      setCogsOverrides({})
      setSavedCogs({})
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e)); setData(null)
    } finally { setLoading(false) }
  }, [mp, lookback])

  useEffect(() => { load() }, [load])

  // Apply COGS overrides to rows for live recalc
  const effectiveResults = useMemo(() => {
    if (!data) return []
    return data.results.map(r => {
      const mnum = r.m_number
      if (mnum && mnum in cogsOverrides) {
        return recalcRow(r, cogsOverrides[mnum])
      }
      return r
    })
  }, [data, cogsOverrides])

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return effectiveResults
      .filter(r => {
        if (q && !r.asin.toLowerCase().includes(q)
            && !(r.m_number ?? '').toLowerCase().includes(q)
            && !(r.blank_normalized ?? '').toLowerCase().includes(q)) return false
        if (onlyLoss && (r.net_profit === null || r.net_profit >= 0)) return false
        if (minConf === 'HIGH' && r.confidence !== 'HIGH') return false
        if (minConf === 'MEDIUM' && r.confidence === 'LOW') return false
        return true
      })
      .slice()
      .sort((a, b) => cmpVals((a as unknown as Record<string, unknown>)[sortKey], (b as unknown as Record<string, unknown>)[sortKey], sortDir))
  }, [effectiveResults, query, onlyLoss, minConf, sortKey, sortDir])

  // Recalculate summary from effective results
  const summary = useMemo(() => {
    const scored = effectiveResults.filter(r => r.net_margin_pct !== null)
    let healthy = 0, thin = 0, unprofitable = 0
    let totalRev = 0, totalProfit = 0
    for (const r of scored) {
      const p = r.net_margin_pct!
      if (p >= 20) healthy++
      else if (p >= 5) thin++
      else unprofitable++
      totalRev += r.net_revenue
      totalProfit += r.net_profit ?? 0
    }
    return {
      total_skus: effectiveResults.length,
      scored_skus: scored.length,
      buckets: { healthy, thin, unprofitable, unknown: effectiveResults.length - scored.length },
      total_net_revenue: Math.round(totalRev * 100) / 100,
      total_net_profit: Math.round(totalProfit * 100) / 100,
    }
  }, [effectiveResults])

  function headerClick(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  async function saveCogs(mNumber: string, costPerUnit: number) {
    setSavingCogs(p => ({ ...p, [mNumber]: true }))
    try {
      const r = await api('/api/cairn/cogs-override/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ m_number: mNumber, cost_price_gbp: costPerUnit }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        alert(`Failed to save: ${j?.error || r.status}`)
      } else {
        setSavedCogs(p => ({ ...p, [mNumber]: true }))
        setTimeout(() => setSavedCogs(p => { const n = { ...p }; delete n[mNumber]; return n }), 2000)
      }
    } catch (e) {
      alert(`Save failed: ${e}`)
    } finally {
      setSavingCogs(p => { const n = { ...p }; delete n[mNumber]; return n })
    }
  }

  const costWarning = useMemo(() => {
    if (!data) return null
    const scored = data.results.filter(r => r.cogs_per_unit !== null)
    if (scored.length < 10) return null
    const uniq = new Set(scored.map(r => r.cogs_per_unit))
    if (uniq.size === 1) {
      const v = Array.from(uniq)[0]
      return `All ${scored.length} SKUs show identical COGS (${money(v, mp)}/unit). Blank costs haven\u2019t been populated \u2014 use the COGS column to override per SKU.`
    }
    return null
  }, [data, mp])

  const s = data ? summary : null
  const b = s?.buckets

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold">Profitability</h1>
          <p className="text-sm text-gray-500">Per-SKU margin. Edit COGS to see live impact on profit. Saved overrides persist.</p>
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
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter ASIN, M# or blank\u2026" className="flex-1 min-w-[140px] border rounded px-2 py-1 text-sm" />
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

      {/* Summary cards — recalculated live from overrides */}
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
              {[
                { key: 'asin', label: 'ASIN' },
                { key: 'm_number', label: 'M#' },
                { key: 'blank_normalized', label: 'Blank' },
                { key: 'units', label: 'Units', right: true },
                { key: 'net_revenue', label: 'Net rev', right: true },
                { key: 'fees_total', label: 'Fees', right: true },
                { key: 'cogs_per_unit', label: 'COGS/unit', right: true },
                { key: 'ad_spend', label: 'Ads', right: true },
                { key: 'net_profit', label: 'Net profit', right: true },
                { key: 'net_margin_pct', label: 'Margin', right: true },
                { key: 'confidence', label: 'Conf' },
              ].map(c => (
                <th key={c.key} onClick={() => headerClick(c.key)}
                  className={`px-3 py-2 cursor-pointer select-none whitespace-nowrap hover:bg-gray-100 ${c.right ? 'text-right' : 'text-left'}`}>
                  {c.label}
                  {sortKey === c.key && <span className="ml-1 text-gray-400">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && <tr><td colSpan={11} className="p-6 text-center text-gray-400">Loading\u2026</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={11} className="p-6 text-center text-gray-400">No rows.</td></tr>}
            {!loading && rows.map(r => {
              const isOverridden = r.m_number != null && r.m_number in cogsOverrides
              return (
                <tr key={`${r.asin}-${r.marketplace}`} className={`hover:bg-gray-50 ${r.confidence === 'LOW' ? 'text-gray-400' : ''} ${isOverridden ? 'bg-blue-50/50' : ''}`}>
                  {/* ASIN */}
                  <td className="px-3 py-2 whitespace-nowrap">{r.asin}</td>
                  {/* M# */}
                  <td className="px-3 py-2 whitespace-nowrap">{r.m_number ?? '\u2014'}</td>
                  {/* Blank */}
                  <td className="px-3 py-2 whitespace-nowrap text-xs text-gray-500" title={r.blank_raw ?? ''}>
                    {r.blank_normalized ?? '\u2014'}
                    {r.is_composite && <span className="ml-1 text-[9px] text-amber-600" title="Composite blank">\u25C6</span>}
                  </td>
                  {/* Units */}
                  <td className="px-3 py-2 whitespace-nowrap text-right">{r.units}</td>
                  {/* Net rev */}
                  <td className="px-3 py-2 whitespace-nowrap text-right">{money(r.net_revenue, mp)}</td>
                  {/* Fees */}
                  <td className="px-3 py-2 whitespace-nowrap text-right">{money(r.fees_total, mp)}</td>
                  {/* COGS/unit — editable */}
                  <td className="px-2 py-1 whitespace-nowrap text-right">
                    <CogsCell
                      row={r}
                      mp={mp}
                      isOverridden={isOverridden}
                      isSaving={!!r.m_number && !!savingCogs[r.m_number]}
                      isSaved={!!r.m_number && !!savedCogs[r.m_number]}
                      onOverride={(val) => {
                        if (!r.m_number) return
                        setCogsOverrides(p => ({ ...p, [r.m_number!]: val }))
                      }}
                      onSave={() => {
                        if (!r.m_number || !(r.m_number in cogsOverrides)) return
                        saveCogs(r.m_number, cogsOverrides[r.m_number])
                      }}
                    />
                  </td>
                  {/* Ads */}
                  <td className="px-3 py-2 whitespace-nowrap text-right">{money(r.ad_spend, mp)}</td>
                  {/* Net profit */}
                  <td className="px-3 py-2 whitespace-nowrap text-right">
                    <span className={r.net_profit === null ? 'text-gray-400' : r.net_profit >= 0 ? 'text-green-700' : 'text-red-700'}>
                      {money(r.net_profit, mp)}
                    </span>
                  </td>
                  {/* Margin */}
                  <td className="px-3 py-2 whitespace-nowrap text-right">
                    <span className={r.net_margin_pct === null ? 'text-gray-400' : r.net_margin_pct >= 20 ? 'text-green-700 font-medium' : r.net_margin_pct >= 5 ? 'text-amber-600' : 'text-red-700 font-medium'}>
                      {pct(r.net_margin_pct)}
                    </span>
                  </td>
                  {/* Confidence */}
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                      r.confidence === 'HIGH' ? 'bg-green-100 text-green-700' :
                      r.confidence === 'MEDIUM' ? 'bg-amber-100 text-amber-700' :
                      'bg-red-100 text-red-700'
                    }`}>
                      {{ HIGH: 'HIGH', MEDIUM: 'MED', LOW: 'LOW' }[r.confidence]}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {data && (
        <p className="mt-3 text-xs text-gray-500">
          Showing <b>{rows.length}</b> of <b>{summary.total_skus}</b> SKUs
          {' \u00b7 '}{data.marketplace} {' \u00b7 '} last {data.lookback_days} days
          {Object.keys(cogsOverrides).length > 0 && (
            <span className="ml-2 text-blue-600">
              \u00b7 {Object.keys(cogsOverrides).length} COGS override{Object.keys(cogsOverrides).length > 1 ? 's' : ''} applied
            </span>
          )}
        </p>
      )}
    </div>
  )
}

// ── COGS editable cell ───────────────────────────────────────────────────────

function CogsCell({ row, mp, isOverridden, isSaving, isSaved, onOverride, onSave }: {
  row: MarginRow
  mp: string
  isOverridden: boolean
  isSaving: boolean
  isSaved: boolean
  onOverride: (val: number) => void
  onSave: () => void
}) {
  const [editing, setEditing] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const displayVal = row.cogs_per_unit

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editing])

  if (!row.m_number) {
    return <span className="text-gray-400">{money(displayVal, mp)}</span>
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="number"
        step="0.01"
        min="0"
        defaultValue={displayVal?.toFixed(2) ?? ''}
        className="w-20 border rounded px-1.5 py-0.5 text-sm text-right"
        onBlur={(e) => {
          setEditing(false)
          const v = parseFloat(e.target.value)
          if (!isNaN(v) && v >= 0) onOverride(v)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            (e.target as HTMLInputElement).blur()
          } else if (e.key === 'Escape') {
            setEditing(false)
          }
        }}
      />
    )
  }

  return (
    <span className="inline-flex items-center gap-1">
      <button
        onClick={() => setEditing(true)}
        className={`hover:underline cursor-pointer ${isOverridden ? 'text-blue-700 font-medium' : ''}`}
        title="Click to edit COGS per unit"
      >
        {money(displayVal, mp)}
      </button>
      {isOverridden && !isSaving && !isSaved && (
        <button
          onClick={onSave}
          className="text-[10px] text-blue-600 hover:text-blue-800 font-medium"
          title="Save override to Manufacture DB"
        >
          save
        </button>
      )}
      {isSaving && <span className="text-[10px] text-gray-400">\u2026</span>}
      {isSaved && <span className="text-[10px] text-green-600">\u2713</span>}
    </span>
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
