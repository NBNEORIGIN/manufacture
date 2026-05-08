'use client'

import { useMemo, useState } from 'react'
import { api } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ParsedRow {
  title: string
  views: number
  clicks: number
  orders: number
  revenue: number
  spend: number
  spend_currency: string  // detected from prefix on the spend cell, falls back to form selector
}

interface ParseResult {
  rows: ParsedRow[]
  errors: string[]
}

interface MatchEntry {
  title_input: string
  title_matched: string
  sku: string | null
  listing_id: number
  m_number: string | null
  state: string                         // 'active' | 'inactive' | 'draft' etc — Etsy's listing state
  match_type: 'exact' | 'case_insensitive' | 'fuzzy' | 'ambiguous'
  confidence: number
}

interface MatchResult {
  matches: MatchEntry[]
  unmatched: string[]
}

interface IngestResult {
  period_start: string
  period_end: string
  source_currency: string
  fx_rate_used: number
  rows_received: number
  rows_upserted: number
  rows_replaced: number
  unknown_listings: number[]
  total_spend_gbp: number
}

// ── Parser ────────────────────────────────────────────────────────────────────

// The Etsy seller-dashboard scrape format (per Toby's paste 2026-05-08):
// Each listing block contains the title (often duplicated), a "." separator,
// "Advertising status" boilerplate, then a tab/multi-space delimited metrics
// row of the form:
//   <views> <clicks> <click_rate%> <orders> <currency$revenue> <currency$spend> <ROAS>
// e.g.:  7,121  164  2.3%  8  US$337.15  US$88.60  3.81
//
// The parser walks lines top-to-bottom looking for metrics rows; for each one
// it walks back to find the first content line above it, ignoring the boiler-
// plate ".", blank lines, and "Advertising status". That line is the title.
//
// Limitations: a listing whose ad spend is reported as "—" or "N/A" instead
// of a number won't match the regex and will be skipped silently. None of the
// rows in Toby's reference paste look like that, so it's not a v1 concern.

function isMetricsLine(line: string): boolean {
  const trimmed = line.trim()
  if (!trimmed) return false
  // Tabs OR runs of 2+ whitespace separate the columns.
  const parts = trimmed.split(/\t+|\s{2,}/)
  if (parts.length < 7) return false
  // First part must be an integer (views) — this is the strongest discriminator.
  if (!/^[\d,]+$/.test(parts[0])) return false
  // Third part must be a percentage (click rate).
  if (!/^[\d.]+%$/.test(parts[2])) return false
  return true
}

function parseMetrics(line: string): Omit<ParsedRow, 'title'> {
  const parts = line.trim().split(/\t+|\s{2,}/)
  // num() strips commas, currency prefixes (US$ / £ / €) and parses to float.
  const num = (s: string) => parseFloat(s.replace(/,/g, '').replace(/[^0-9.\-]/g, '')) || 0
  const detectCurrency = (s: string): string => {
    if (/US\$/i.test(s)) return 'USD'
    if (/€/.test(s)) return 'EUR'
    if (/£|GB£/.test(s)) return 'GBP'
    return ''
  }
  return {
    views:   Math.round(num(parts[0])),
    clicks:  Math.round(num(parts[1])),
    // parts[2] is click rate — derivable from views/clicks, not stored
    orders:  Math.round(num(parts[3])),
    revenue: num(parts[4]),
    spend:   num(parts[5]),
    spend_currency: detectCurrency(parts[5]) || detectCurrency(parts[4]),
  }
}

function parseEtsyAds(raw: string, defaultCurrency: string): ParseResult {
  const lines = raw.split(/\r?\n/)
  const rows: ParsedRow[] = []
  const errors: string[] = []

  for (let i = 0; i < lines.length; i++) {
    if (!isMetricsLine(lines[i])) continue

    // Walk backwards to find title — first non-junk content line.
    let title = ''
    for (let j = i - 1; j >= 0; j--) {
      const t = lines[j].trim()
      if (!t || t === '.' || t === 'Advertising status') continue
      // Skip lines that look like the previous block's metrics row.
      if (isMetricsLine(lines[j])) break
      title = t
      break
    }

    if (!title) {
      errors.push(`Line ${i + 1}: metrics row found but no title above it`)
      continue
    }

    const m = parseMetrics(lines[i])
    rows.push({
      title,
      ...m,
      spend_currency: m.spend_currency || defaultCurrency,
    })
  }

  return { rows, errors }
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function EtsyAdsUploadPage() {
  const [raw, setRaw] = useState('')
  // Default the period to "last full month" — most common workflow.
  const defaultStart = useMemo(() => {
    const d = new Date()
    return new Date(d.getFullYear(), d.getMonth() - 1, 1).toISOString().slice(0, 10)
  }, [])
  const defaultEnd = useMemo(() => {
    const d = new Date()
    return new Date(d.getFullYear(), d.getMonth(), 0).toISOString().slice(0, 10)
  }, [])
  const [periodStart, setPeriodStart] = useState(defaultStart)
  const [periodEnd, setPeriodEnd] = useState(defaultEnd)
  const [currency, setCurrency] = useState('USD')

  const [matching, setMatching] = useState(false)
  const [matchResult, setMatchResult] = useState<MatchResult | null>(null)
  const [matchErr, setMatchErr] = useState<string | null>(null)

  const [submitting, setSubmitting] = useState(false)
  const [ingestResult, setIngestResult] = useState<IngestResult | null>(null)
  const [submitErr, setSubmitErr] = useState<string | null>(null)

  // Manual title→listing_id overrides keyed by the *input* title (to handle
  // ambiguous matches Toby resolves by hand). Empty value = drop the row.
  const [overrides, setOverrides] = useState<Record<string, number | null>>({})

  // Parse the textarea live as Toby pastes — instant feedback.
  const parsed = useMemo(() => parseEtsyAds(raw, currency), [raw, currency])

  const totalSpend = useMemo(
    () => parsed.rows.reduce((s, r) => s + r.spend, 0),
    [parsed.rows],
  )

  async function previewMatches() {
    setMatching(true)
    setMatchErr(null)
    setMatchResult(null)
    setIngestResult(null)
    try {
      const r = await api('/api/cairn/etsy/listings/lookup-by-title/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ titles: parsed.rows.map(row => row.title) }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        throw new Error(j?.detail || j?.error || `HTTP ${r.status}`)
      }
      setMatchResult(await r.json() as MatchResult)
    } catch (e) {
      setMatchErr(e instanceof Error ? e.message : String(e))
    } finally {
      setMatching(false)
    }
  }

  // Build the resolved row set: take parsed rows, drop unmatched, apply
  // any manual overrides Toby's dialled in. Returns rows ready to ship to
  // the ingest endpoint.
  const resolvedRows = useMemo(() => {
    if (!matchResult) return []
    const byInput = new Map<string, MatchEntry>()
    for (const m of matchResult.matches) {
      byInput.set(m.title_input, m)
    }
    return parsed.rows
      .map(row => {
        // Manual override wins over server match.
        if (row.title in overrides) {
          const ov = overrides[row.title]
          if (ov === null) return null  // explicitly dropped
          return { ...row, listing_id: ov }
        }
        const m = byInput.get(row.title)
        if (!m) return null
        // Skip ambiguous unless overridden.
        if (m.match_type === 'ambiguous') return null
        return { ...row, listing_id: m.listing_id }
      })
      .filter((r): r is ParsedRow & { listing_id: number } => r !== null)
  }, [parsed.rows, matchResult, overrides])

  async function confirmSave() {
    if (resolvedRows.length === 0) {
      setSubmitErr('No matched rows to upload')
      return
    }
    setSubmitting(true)
    setSubmitErr(null)
    setIngestResult(null)
    try {
      const r = await api('/api/cairn/etsy/ad-spend/ingest/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          period_start: periodStart,
          period_end:   periodEnd,
          source_currency: currency,
          source: 'manual_paste_v1',
          rows: resolvedRows.map(r => ({
            listing_id:     r.listing_id,
            views:          r.views,
            clicks:         r.clicks,
            orders_attrib:  r.orders,
            revenue_attrib: r.revenue,
            spend:          r.spend,
          })),
        }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        throw new Error(j?.detail || j?.error || `HTTP ${r.status}`)
      }
      setIngestResult(await r.json() as IngestResult)
    } catch (e) {
      setSubmitErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  // Group server matches by status for display.
  const matchGroups = useMemo(() => {
    if (!matchResult) return null
    const exact:    MatchEntry[] = []
    const fuzzy:    MatchEntry[] = []
    const ambiguous:MatchEntry[] = []
    const inactive: MatchEntry[] = []
    for (const m of matchResult.matches) {
      if (m.state && m.state !== 'active') inactive.push(m)
      if (m.match_type === 'exact' || m.match_type === 'case_insensitive') exact.push(m)
      else if (m.match_type === 'fuzzy') fuzzy.push(m)
      else ambiguous.push(m)
    }
    return { exact, fuzzy, ambiguous, inactive, unmatched: matchResult.unmatched }
  }, [matchResult])

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-xl font-semibold">Etsy Ads — Upload</h1>
        <p className="text-sm text-gray-500">
          Paste the per-listing stats from Etsy seller dashboard → Marketing → Etsy Ads. The parser
          extracts title + spend per row, matches each title to a listing in Deek, and writes the
          spend through to the margin engine. Idempotent — re-uploading the same period replaces.
        </p>
      </div>

      {/* Inputs */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3 bg-white border rounded-lg p-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500">Period start</span>
          <input
            type="date"
            value={periodStart}
            onChange={e => setPeriodStart(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500">Period end</span>
          <input
            type="date"
            value={periodEnd}
            onChange={e => setPeriodEnd(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500">Source currency (Etsy dashboard default is USD)</span>
          <select
            value={currency}
            onChange={e => setCurrency(e.target.value)}
            className="border rounded px-2 py-1 text-sm bg-white"
          >
            <option value="USD">USD</option>
            <option value="GBP">GBP</option>
            <option value="EUR">EUR</option>
          </select>
        </label>
      </div>

      {/* Paste area */}
      <div className="bg-white border rounded-lg p-3 mb-3">
        <label className="block text-xs text-gray-500 mb-1">
          Paste from Etsy dashboard (select all rows in the listing-stats table, copy, paste here)
        </label>
        <textarea
          value={raw}
          onChange={e => setRaw(e.target.value)}
          rows={10}
          className="w-full border rounded px-2 py-1 text-xs font-mono"
          placeholder={'Title\n.\nAdvertising status\n7,121\t164\t2.3%\t8\tUS$337.15\tUS$88.60\t3.81\n…'}
        />
        <div className="mt-2 flex items-center justify-between text-xs">
          <span className="text-gray-500">
            Parsed: <strong>{parsed.rows.length}</strong> row{parsed.rows.length === 1 ? '' : 's'}
            {parsed.errors.length > 0 && (
              <span className="ml-3 text-amber-700">· {parsed.errors.length} parse warning{parsed.errors.length === 1 ? '' : 's'}</span>
            )}
            {parsed.rows.length > 0 && (
              <span className="ml-3 text-gray-600">
                · total spend <strong>{currency} {totalSpend.toFixed(2)}</strong>
              </span>
            )}
          </span>
          <button
            onClick={previewMatches}
            disabled={matching || parsed.rows.length === 0}
            className="text-sm px-3 py-1.5 border rounded bg-blue-50 hover:bg-blue-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {matching ? 'Matching…' : 'Preview matches'}
          </button>
        </div>
        {parsed.errors.length > 0 && (
          <details className="mt-2 text-xs text-amber-700">
            <summary className="cursor-pointer hover:underline">Show parse warnings</summary>
            <ul className="mt-1 ml-4 list-disc">
              {parsed.errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          </details>
        )}
      </div>

      {/* Errors */}
      {matchErr && (
        <div className="mb-3 border border-red-300 bg-red-50 rounded-lg p-3 text-sm text-red-900">
          Match failed: {matchErr}
        </div>
      )}

      {/* Match results */}
      {matchGroups && (
        <div className="mb-3 bg-white border rounded-lg overflow-hidden">
          <div className="px-3 py-2 bg-gray-50 border-b text-xs font-medium text-gray-600">
            Title-match preview
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 p-3 text-xs">
            <Tile label="Exact / case-match" count={matchGroups.exact.length} cls="text-green-700" />
            <Tile label="Fuzzy match" count={matchGroups.fuzzy.length} cls="text-amber-700" />
            <Tile label="Ambiguous (resolve)" count={matchGroups.ambiguous.length} cls="text-orange-700" />
            <Tile label="Inactive listing" count={matchGroups.inactive.length} cls={matchGroups.inactive.length > 0 ? 'text-purple-700' : 'text-gray-400'} />
            <Tile label="Unmatched (skipped)" count={matchGroups.unmatched.length} cls="text-red-700" />
          </div>

          {matchGroups.inactive.length > 0 && (
            <details className="border-t">
              <summary className="px-3 py-2 cursor-pointer text-xs font-medium text-purple-800 bg-purple-50/50 hover:bg-purple-50">
                Inactive listings — these matched but the Etsy listing is no longer active. Spend will still record, but be aware they won't appear in current margin views.
              </summary>
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500 uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-1.5 text-left">Title</th>
                    <th className="px-3 py-1.5 text-left">M#</th>
                    <th className="px-3 py-1.5 text-left">SKU</th>
                    <th className="px-3 py-1.5 text-left">State</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {matchGroups.inactive.map((m, i) => (
                    <tr key={i}>
                      <td className="px-3 py-1.5 max-w-[40ch] truncate" title={m.title_input}>{m.title_input}</td>
                      <td className="px-3 py-1.5 font-mono">{m.m_number ?? '—'}</td>
                      <td className="px-3 py-1.5 font-mono">{m.sku ?? '—'}</td>
                      <td className="px-3 py-1.5 text-purple-700 font-medium">{m.state}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}

          {matchGroups.fuzzy.length > 0 && (
            <details open className="border-t">
              <summary className="px-3 py-2 cursor-pointer text-xs font-medium text-amber-800 bg-amber-50/50 hover:bg-amber-50">
                Fuzzy matches — review before submitting
              </summary>
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500 uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-1.5 text-left">Pasted title</th>
                    <th className="px-3 py-1.5 text-left">Matched to</th>
                    <th className="px-3 py-1.5 text-left">M#</th>
                    <th className="px-3 py-1.5 text-left">SKU</th>
                    <th className="px-3 py-1.5 text-left">State</th>
                    <th className="px-3 py-1.5 text-right">Confidence</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {matchGroups.fuzzy.map((m, i) => (
                    <tr key={i}>
                      <td className="px-3 py-1.5 text-gray-700 max-w-[40ch] truncate" title={m.title_input}>{m.title_input}</td>
                      <td className="px-3 py-1.5 text-gray-700 max-w-[40ch] truncate" title={m.title_matched}>{m.title_matched}</td>
                      <td className="px-3 py-1.5 font-mono">{m.m_number ?? '—'}</td>
                      <td className="px-3 py-1.5 font-mono">{m.sku ?? '—'}</td>
                      <td className={`px-3 py-1.5 ${m.state !== 'active' ? 'text-purple-700 font-medium' : 'text-gray-500'}`}>{m.state}</td>
                      <td className="px-3 py-1.5 text-right">{(m.confidence * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}

          {matchGroups.unmatched.length > 0 && (
            <details className="border-t">
              <summary className="px-3 py-2 cursor-pointer text-xs font-medium text-red-800 bg-red-50/50 hover:bg-red-50">
                Unmatched titles ({matchGroups.unmatched.length}) — these rows will be skipped
              </summary>
              <ul className="px-3 py-2 text-xs text-gray-700 space-y-1 max-h-60 overflow-y-auto">
                {matchGroups.unmatched.map((t, i) => (
                  <li key={i} className="font-mono">{t}</li>
                ))}
              </ul>
            </details>
          )}

          <div className="px-3 py-2 border-t bg-gray-50 flex items-center justify-between text-xs">
            <span className="text-gray-600">
              <strong>{resolvedRows.length}</strong> rows ready to submit ·
              total spend <strong>{currency} {resolvedRows.reduce((s, r) => s + r.spend, 0).toFixed(2)}</strong>
            </span>
            <button
              onClick={confirmSave}
              disabled={submitting || resolvedRows.length === 0}
              className="text-sm px-3 py-1.5 border rounded bg-green-50 hover:bg-green-100 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? 'Uploading…' : 'Confirm & save'}
            </button>
          </div>
        </div>
      )}

      {/* Submit error / success */}
      {submitErr && (
        <div className="mb-3 border border-red-300 bg-red-50 rounded-lg p-3 text-sm text-red-900">
          Upload failed: {submitErr}
        </div>
      )}
      {ingestResult && (
        <div className="mb-3 border border-green-300 bg-green-50 rounded-lg p-3 text-sm text-green-900 space-y-1">
          <div>
            <strong>✓ Uploaded</strong> {ingestResult.rows_upserted} row{ingestResult.rows_upserted === 1 ? '' : 's'}
            {ingestResult.rows_replaced > 0 && <> ({ingestResult.rows_replaced} replaced existing data)</>} —
            total <strong>£{ingestResult.total_spend_gbp.toFixed(2)}</strong>
            {' '}at FX <strong>{ingestResult.fx_rate_used.toFixed(4)}</strong> {ingestResult.source_currency}→GBP.
          </div>
          {ingestResult.unknown_listings.length > 0 && (
            <div className="text-amber-800">
              ⚠ {ingestResult.unknown_listings.length} row{ingestResult.unknown_listings.length === 1 ? '' : 's'} skipped — listing_id not in Deek:
              {' '}<span className="font-mono">{ingestResult.unknown_listings.join(', ')}</span>
            </div>
          )}
          <div>
            Open <a href="/cairn/profitability" className="underline hover:text-green-700">Profitability</a> and select Etsy or All channels — net profit numbers now reflect this ad spend.
          </div>
        </div>
      )}
    </div>
  )
}

function Tile({ label, count, cls }: { label: string; count: number; cls?: string }) {
  return (
    <div className="bg-white border rounded p-2">
      <div className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`text-lg font-semibold mt-0.5 ${cls ?? 'text-gray-900'}`}>{count}</div>
    </div>
  )
}
