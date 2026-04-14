'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/api'

// ─── Types (mirror core/amazon_intel/margin/quartile_brief.py) ─────────────

type Action = 'PAUSE' | 'REDUCE' | 'INCREASE' | 'HOLD'

interface Recommendation {
  asin: string
  sku: string | null
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

  // Initial load on mount
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

  const downloadCsv = useCallback(async () => {
    const params = new URLSearchParams({
      marketplace,
      lookback_days: String(lookbackDays),
      target_margin_pct: String(targetMarginPct),
      non_ad_cost_pct: String(nonAdCostPct),
      format: 'csv',
    })
    try {
      const r = await api(`/api/cairn/quartile-brief/?${params}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      // Pick up the server-supplied filename if present; fall back to a sane default.
      const disp = r.headers.get('content-disposition') || ''
      const match = disp.match(/filename="([^"]+)"/)
      const filename = match ? match[1] : `quartile-brief-${marketplace || 'all'}.csv`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e: any) {
      setError(`Download failed: ${e?.message || e}`)
    }
  }, [marketplace, lookbackDays, targetMarginPct, nonAdCostPct])

  const recs = brief?.recommendations ?? []
  const grouped = useMemo(() => {
    const out: Record<Action, Recommendation[]> = {
      PAUSE: [], REDUCE: [], INCREASE: [], HOLD: [],
    }
    for (const r of recs) out[r.action].push(r)
    return out
  }, [recs])

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
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
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
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Target margin %</label>
            <input
              type="number" min={0} max={50} step="0.5"
              value={targetMarginPct * 100}
              onChange={(e) => setTargetMarginPct((Number(e.target.value) || 0) / 100)}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Non-ad cost %</label>
            <input
              type="number" min={0} max={100} step="1"
              value={nonAdCostPct * 100}
              onChange={(e) => setNonAdCostPct((Number(e.target.value) || 0) / 100)}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
            />
          </div>
          <div className="flex items-end gap-2">
            <button
              onClick={fetchBrief}
              disabled={loading}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm px-4 py-1.5 rounded"
            >
              {loading ? 'Loading…' : 'Refresh'}
            </button>
            <button
              onClick={copyAsEmail}
              disabled={loading || !brief}
              className="bg-gray-100 hover:bg-gray-200 disabled:bg-gray-50 disabled:text-gray-400 text-sm text-gray-800 px-3 py-1.5 rounded border border-gray-300"
              title="Copy email-ready text to clipboard"
            >
              {copied ? 'Copied ✓' : 'Copy as email'}
            </button>
            <button
              onClick={downloadCsv}
              disabled={loading || !brief}
              className="bg-gray-100 hover:bg-gray-200 disabled:bg-gray-50 disabled:text-gray-400 text-sm text-gray-800 px-3 py-1.5 rounded border border-gray-300"
              title="Download recommendations as CSV"
            >
              Download CSV
            </button>
            <button
              onClick={triggerSync}
              disabled={syncing}
              className="bg-gray-100 hover:bg-gray-200 disabled:bg-gray-50 disabled:text-gray-400 text-sm text-gray-800 px-3 py-1.5 rounded border border-gray-300"
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
            const rows = grouped[action]
            if (rows.length === 0) return null
            return (
              <div key={action} className="bg-white border border-gray-200 rounded-md">
                <header className="px-4 py-2 border-b border-gray-200 flex items-center gap-2">
                  <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded border ${actionBadge(action)}`}>
                    {action}
                  </span>
                  <span className="text-sm text-gray-600">{rows.length} SKU{rows.length === 1 ? '' : 's'}</span>
                </header>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 text-xs text-gray-600">
                      <tr>
                        <th className="text-left px-3 py-2">SKU</th>
                        <th className="text-left px-3 py-2">ASIN</th>
                        <th className="text-left px-3 py-2">Account</th>
                        <th className="text-right px-3 py-2">Spend</th>
                        <th className="text-right px-3 py-2">Ad sales</th>
                        <th className="text-right px-3 py-2">Revenue</th>
                        <th className="text-right px-3 py-2">Units</th>
                        <th className="text-right px-3 py-2">ACOS</th>
                        <th className="text-right px-3 py-2">Recommended</th>
                        <th className="text-right px-3 py-2">Organic</th>
                        <th className="text-left px-3 py-2">Reason / Caveats</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={`${r.asin}-${r.country_code}-${r.account_name}`} className="border-t border-gray-100">
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
