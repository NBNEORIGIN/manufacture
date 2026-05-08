'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface MarginRow {
  asin: string
  marketplace: string
  m_number: string | null
  skus: string[]
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
  // Frontend-only: true when fees_total was filled by the personalised
  // fallback estimator (net_revenue × 0.255) rather than by an actual
  // SP-API getMyFeesEstimate snapshot. Lets the UI mark the value as
  // an estimate so staff don't read it as ground truth.
  fees_estimated?: boolean
}

// Top-loss-maker rows are a sparse subset of MarginRow — only the
// fields the bleeders panel needs. Deek populates these on every
// margin endpoint response (commit 12e7ac7). Up to 5 per response.
interface LossMaker {
  asin: string
  m_number: string | null
  marketplace: string
  units: number
  net_revenue: number
  net_profit: number
  net_margin_pct: number | null
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
}

interface Summary {
  total_skus: number
  scored_skus: number
  buckets: { healthy: number; thin: number; unprofitable: number; unknown: number }
  total_net_revenue: number
  total_net_profit: number
  // Both fields are populated by Cairn's margin endpoints (commit 12e7ac7).
  // total_loss_bleed is the negative-only sum of net_profit (≤0).
  // top_loss_makers is the 5 worst by absolute £ loss for that response.
  total_loss_bleed?: number
  top_loss_makers?: LossMaker[]
}

interface MarginResponse {
  marketplace: string
  lookback_days: number
  summary: Summary
  results: MarginRow[]
}

// ── Constants ─────────────────────────────────────────────────────────────────

const MARKETPLACES = [
  { code: 'ALL', label: 'All channels (combined)' },
  { code: 'UK', label: 'UK' },
  { code: 'DE', label: 'DE' },
  { code: 'FR', label: 'FR' },
  { code: 'IT', label: 'IT' },
  { code: 'ES', label: 'ES' },
  { code: 'NL', label: 'NL' },
  { code: 'US', label: 'US' },
  { code: 'CA', label: 'CA' },
  { code: 'AU', label: 'AU' },
  { code: 'ETSY', label: 'Etsy' },
]

// Codes that represent a single marketplace (used to fan-out the combined view).
const SINGLE_MARKETPLACES = MARKETPLACES.filter(m => m.code !== 'ALL').map(m => m.code)

// Map a marketplace code to the right Cairn margin endpoint. Etsy lives
// at /etsy/margin/per-sku; everything else is /ami/margin/per-sku with a
// `marketplace` query param. Response shape is field-for-field identical
// (Deek commit e137d71) so the rest of the parse path is shared.
function marginEndpoint(code: string, lookback: number): string {
  if (code === 'ETSY') {
    return `/api/cairn/etsy/margin/per-sku/?lookback_days=${lookback}`
  }
  return `/api/cairn/margin/per-sku/?marketplace=${code}&lookback_days=${lookback}`
}

const LOOKBACKS = [
  { days: 7, label: '7d' },
  { days: 30, label: '30d' },
  { days: 90, label: '90d' },
]

// Cairn's /ami/margin/per-sku endpoint converts every monetary field
// (revenue, fees, ad_spend, gross/net profit, margin %) to GBP using a
// daily FX snapshot before returning, regardless of the `marketplace`
// query param. So every number on this page is in GBP — formatting
// with the marketplace-native symbol ($ / € / etc) was a pre-FX-fix
// holdover that mislabelled the values without changing the maths.
//
// Until Cairn's response includes a `currency` field per row, hardcoding
// GBP is the only correct option. If Cairn ever switches to native-
// currency on a per-row basis (unlikely — the analysis-session needs
// like-for-like cross-marketplace comparison in one currency), this
// becomes a per-row read of `r.currency` instead.
const CURRENCY: Record<string, string> = {
  ALL: 'GBP',
  UK: 'GBP', DE: 'GBP', FR: 'GBP', IT: 'GBP', ES: 'GBP', NL: 'GBP',
  US: 'GBP', CA: 'GBP', AU: 'GBP',
  ETSY: 'GBP',
}

type SortKey = string
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

// Estimated fee rate for personalised SKUs whose Cairn fee snapshot is
// missing or null. Toby's heuristic: Amazon's combined referral + FBA fees
// typically run ~25.5% of net revenue on this product range, so fall back
// to that figure rather than reporting zero (which over-states profit and
// makes the row look healthier than it actually is).
const ESTIMATED_FEE_RATE = 0.255

// Apply the estimator to a row that's both personalised AND missing fees.
// Returns the row with fees_total / fees_per_unit / gross_profit /
// net_profit / margins recomputed, plus a `fees_estimated: true` flag so
// the UI can mark the value as a fallback rather than a hard SP-API number.
function estimateFeesForPersonalised(r: MarginRow): MarginRow {
  const feesTotal = Math.round(r.net_revenue * ESTIMATED_FEE_RATE * 100) / 100
  const feesPerUnit = r.units > 0 ? Math.round((feesTotal / r.units) * 100) / 100 : null
  const cogsTotal = r.cogs_total ?? 0
  const grossProfit = r.net_revenue - feesTotal - cogsTotal
  const netProfit = grossProfit - r.ad_spend
  const grossMarginPct = r.net_revenue > 0 ? (grossProfit / r.net_revenue) * 100 : null
  const netMarginPct = r.net_revenue > 0 ? (netProfit / r.net_revenue) * 100 : null
  return {
    ...r,
    fees_total: feesTotal,
    fees_per_unit: feesPerUnit,
    fees_estimated: true,
    gross_profit: r.cogs_per_unit !== null ? Math.round(grossProfit * 100) / 100 : null,
    gross_margin_pct: r.cogs_per_unit !== null && grossMarginPct !== null ? Math.round(grossMarginPct * 100) / 100 : null,
    net_profit: r.cogs_per_unit !== null ? Math.round(netProfit * 100) / 100 : null,
    net_margin_pct: r.cogs_per_unit !== null && netMarginPct !== null ? Math.round(netMarginPct * 100) / 100 : null,
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
  // Ivan #20: 3-state. 'all' = no filter. 'yes' = personalised only. 'no' =
  // non-personalised only. Both 'yes' and 'no' scope the summary tiles.
  const [personalisedFilter, setPersonalisedFilter] = useState<'all' | 'yes' | 'no'>('all')
  // M-number range filter — both inclusive. Empty string = no bound on
  // that side. Parses M0001-style strings to ints by stripping the M.
  const [mFromStr, setMFromStr] = useState('')
  const [mToStr, setMToStr] = useState('')
  const [minConf, setMinConf] = useState<'ANY' | 'MEDIUM' | 'HIGH'>('ANY')
  const [sortKey, setSortKey] = useState<SortKey>('net_profit')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  // Parse the M-range strings to numbers (stripping leading "M" if the user
  // typed it). Empty / invalid → null = no bound on that side.
  const mFromNum = useMemo(() => {
    const cleaned = mFromStr.trim().replace(/^[mM]/, '')
    const n = parseInt(cleaned, 10)
    return Number.isFinite(n) ? n : null
  }, [mFromStr])
  const mToNum = useMemo(() => {
    const cleaned = mToStr.trim().replace(/^[mM]/, '')
    const n = parseInt(cleaned, 10)
    return Number.isFinite(n) ? n : null
  }, [mToStr])

  // Extract numeric M-number from a row's m_number string. Returns null when
  // the m_number is missing or doesn't follow the M#### pattern (so the
  // row is excluded from any active range filter — never silently included).
  const mNumOf = (m: string | null): number | null => {
    if (!m) return null
    const match = m.match(/^M0*(\d+)$/i)
    return match ? parseInt(match[1], 10) : null
  }

  // Ivan #20: which M-numbers are personalised — fetched once, used to flag rows.
  const [personalisedMNumbers, setPersonalisedMNumbers] = useState<Set<string>>(new Set())
  useEffect(() => {
    api('/api/d2c/personalised/m-numbers/')
      .then(r => r.ok ? r.json() : { m_numbers: [] })
      .then(d => setPersonalisedMNumbers(new Set(d.m_numbers || [])))
      .catch(() => {/* leave as empty — column just shows blank ticks */})
  }, [])

  // When mp === 'ALL' we couldn't return a partial picture if some
  // marketplaces fail — surface which ones errored so the totals make sense.
  const [partialErrors, setPartialErrors] = useState<{ marketplace: string; error: string }[]>([])

  const load = useCallback(async () => {
    setLoading(true); setErr(null); setPartialErrors([])
    try {
      if (mp === 'ALL') {
        // Fan out across every single marketplace in parallel and concat
        // the results. Each row keeps its own `marketplace` tag, so the
        // table row keys remain unique and the per-row marketplace cell
        // shows where each row came from. Summary tiles already aggregate
        // by sum, so they work for combined view automatically.
        //
        // We do NOT fail the whole view if one marketplace errors —
        // partial coverage is more useful than nothing. Errors surface
        // in a banner above the table.
        const settled = await Promise.allSettled(
          SINGLE_MARKETPLACES.map(async code => {
            const r = await api(marginEndpoint(code, lookback))
            if (!r.ok) {
              const j = await r.json().catch(() => ({}))
              throw new Error(j?.detail || j?.error || `HTTP ${r.status}`)
            }
            return await r.json() as MarginResponse
          }),
        )
        const errors: { marketplace: string; error: string }[] = []
        const results: MarginRow[] = []
        // Aggregate server-provided loss-bleed totals + top-loss-makers
        // across all per-marketplace responses. We sum the bleed and
        // union the top-5-per-marketplace lists, then re-sort to keep
        // the worst across the whole estate. (Recomputing client-side
        // from results would also work but would ignore Cairn's
        // confidence/scoring logic — better to trust the server.)
        let aggBleed = 0
        const aggBleeders: LossMaker[] = []
        settled.forEach((s, i) => {
          const code = SINGLE_MARKETPLACES[i]
          if (s.status === 'fulfilled') {
            results.push(...s.value.results)
            const sb = s.value.summary?.total_loss_bleed
            if (typeof sb === 'number') aggBleed += sb
            const tlm = s.value.summary?.top_loss_makers
            if (Array.isArray(tlm)) aggBleeders.push(...tlm)
          } else {
            errors.push({ marketplace: code, error: s.reason instanceof Error ? s.reason.message : String(s.reason) })
          }
        })
        setData({
          marketplace: 'ALL',
          lookback_days: lookback,
          // Tiles that depend on results (revenue / profit / buckets)
          // are recomputed client-side from `effectiveResults` — the
          // placeholder zeros below are ignored. Loss-bleed and
          // top-loss-makers DO come from this object (server-aggregated)
          // since they're advisory and can't sensibly be recomputed
          // when client-side COGS overrides are in play.
          summary: {
            total_skus: results.length, scored_skus: 0,
            buckets: { healthy: 0, thin: 0, unprofitable: 0, unknown: 0 },
            total_net_revenue: 0, total_net_profit: 0,
            total_loss_bleed: aggBleed,
            top_loss_makers: aggBleeders
              .slice()
              .sort((a, b) => Math.abs(b.net_profit) - Math.abs(a.net_profit))
              .slice(0, 5),
          },
          results,
        })
        setPartialErrors(errors)
      } else {
        const r = await api(marginEndpoint(mp, lookback))
        if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j?.detail || j?.error || `HTTP ${r.status}`) }
        setData(await r.json() as MarginResponse)
      }
      setCogsOverrides({})
      setSavedCogs({})
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e)); setData(null)
    } finally { setLoading(false) }
  }, [mp, lookback])

  useEffect(() => { load() }, [load])

  // Apply (in order): personalised fee fallback, COGS overrides,
  // computed avg_price. Order matters — fees come first so the COGS
  // override step uses the estimated fees when computing margin.
  const effectiveResults = useMemo(() => {
    if (!data) return []
    return data.results.map(r => {
      let row = r
      const mnum = r.m_number
      const isPersonalised = !!(mnum && personalisedMNumbers.has(mnum))
      const noFees = row.fees_total === null || row.fees_total === 0
      if (isPersonalised && noFees && row.net_revenue > 0) {
        row = estimateFeesForPersonalised(row)
      }
      if (mnum && mnum in cogsOverrides) {
        row = recalcRow(row, cogsOverrides[mnum])
      }
      return { ...row, avg_price: row.units > 0 ? Math.round((row.gross_revenue / row.units) * 100) / 100 : null } as MarginRow & { avg_price: number | null }
    })
  }, [data, cogsOverrides, personalisedMNumbers])

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return effectiveResults
      .filter(r => {
        if (q && !r.asin.toLowerCase().includes(q)
            && !(r.m_number ?? '').toLowerCase().includes(q)
            && !(r.skus ?? []).some(s => s.toLowerCase().includes(q))
            && !(r.blank_normalized ?? '').toLowerCase().includes(q)) return false
        if (onlyLoss && (r.net_profit === null || r.net_profit >= 0)) return false
        if (personalisedFilter === 'yes' && !(r.m_number && personalisedMNumbers.has(r.m_number))) return false
        if (personalisedFilter === 'no'  &&  (r.m_number && personalisedMNumbers.has(r.m_number))) return false
        if (mFromNum !== null || mToNum !== null) {
          const n = mNumOf(r.m_number)
          if (n === null) return false
          if (mFromNum !== null && n < mFromNum) return false
          if (mToNum !== null && n > mToNum) return false
        }
        if (minConf === 'HIGH' && r.confidence !== 'HIGH') return false
        if (minConf === 'MEDIUM' && r.confidence === 'LOW') return false
        return true
      })
      .slice()
      .sort((a, b) => cmpVals((a as unknown as Record<string, unknown>)[sortKey], (b as unknown as Record<string, unknown>)[sortKey], sortDir))
  }, [effectiveResults, query, onlyLoss, personalisedFilter, personalisedMNumbers, mFromNum, mToNum, minConf, sortKey, sortDir])

  // Summary scope: by default the tiles reflect ALL SKUs returned by the
  // endpoint (revenue is real regardless of margin calc — original intent).
  // But when the user enables a "view-scoping" filter — Personalised only,
  // Loss-makers only, or a minimum confidence threshold — the tiles narrow
  // to that group so the page works as a focused-analysis view (Ivan #20:
  // "determine [personalised] profitability as a separate group").
  //
  // The text-search query box is treated as exploration, NOT scope —
  // typing "M0634" doesn't crater the Net revenue tile to one SKU.
  const summarySource = useMemo(() => {
    return effectiveResults.filter(r => {
      if (onlyLoss && (r.net_profit === null || r.net_profit >= 0)) return false
      if (personalisedFilter === 'yes' && !(r.m_number && personalisedMNumbers.has(r.m_number))) return false
      if (personalisedFilter === 'no'  &&  (r.m_number && personalisedMNumbers.has(r.m_number))) return false
      if (mFromNum !== null || mToNum !== null) {
        const n = mNumOf(r.m_number)
        if (n === null) return false
        if (mFromNum !== null && n < mFromNum) return false
        if (mToNum !== null && n > mToNum) return false
      }
      if (minConf === 'HIGH' && r.confidence !== 'HIGH') return false
      if (minConf === 'MEDIUM' && r.confidence === 'LOW') return false
      return true
    })
  }, [effectiveResults, onlyLoss, personalisedFilter, personalisedMNumbers, mFromNum, mToNum, minConf])

  const summary = useMemo(() => {
    const scored = summarySource.filter(r => r.net_margin_pct !== null)
    let healthy = 0, thin = 0, unprofitable = 0
    let totalProfit = 0
    let totalBleed = 0
    for (const r of scored) {
      const p = r.net_margin_pct!
      if (p >= 20) healthy++
      else if (p >= 5) thin++
      else unprofitable++
      totalProfit += r.net_profit ?? 0
      // Loss bleed = sum of negative net_profit only (Deek convention).
      // Always ≤ 0. Recomputed client-side so it respects active
      // scope filters and any pending COGS overrides.
      if ((r.net_profit ?? 0) < 0) totalBleed += r.net_profit!
    }
    // Top 5 bleeders by absolute £ loss, computed from the same source.
    const bleeders: LossMaker[] = scored
      .filter(r => (r.net_profit ?? 0) < 0)
      .sort((a, b) => (a.net_profit ?? 0) - (b.net_profit ?? 0))
      .slice(0, 5)
      .map(r => ({
        asin: r.asin,
        m_number: r.m_number,
        marketplace: r.marketplace,
        units: r.units,
        net_revenue: r.net_revenue,
        net_profit: r.net_profit ?? 0,
        net_margin_pct: r.net_margin_pct,
        confidence: r.confidence,
      }))
    const totalRev = summarySource.reduce((sum, r) => sum + r.net_revenue, 0)
    return {
      total_skus: summarySource.length,
      scored_skus: scored.length,
      buckets: { healthy, thin, unprofitable, unknown: summarySource.length - scored.length },
      total_net_revenue: Math.round(totalRev * 100) / 100,
      total_net_profit: Math.round(totalProfit * 100) / 100,
      total_loss_bleed: Math.round(totalBleed * 100) / 100,
      top_loss_makers: bleeders,
    }
  }, [summarySource])

  // Build a short label describing the active scope, shown next to the tiles
  // so the user can see at a glance what subset they're looking at.
  const scopeLabel = useMemo(() => {
    const parts: string[] = []
    if (personalisedFilter === 'yes') parts.push('Personalised')
    else if (personalisedFilter === 'no') parts.push('Non-personalised')
    if (mFromNum !== null && mToNum !== null) parts.push(`M${mFromNum}–M${mToNum}`)
    else if (mFromNum !== null) parts.push(`M${mFromNum}+`)
    else if (mToNum !== null) parts.push(`up to M${mToNum}`)
    if (onlyLoss) parts.push('Loss-makers')
    if (minConf === 'HIGH') parts.push('HIGH confidence')
    else if (minConf === 'MEDIUM') parts.push('MEDIUM+ confidence')
    return parts.join(' · ')
  }, [personalisedFilter, mFromNum, mToNum, onlyLoss, minConf])

  function headerClick(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  async function saveCogs(mNumber: string, costPerUnit: number) {
    setSavingCogs(p => ({ ...p, [mNumber]: true }))
    try {
      // 2026-05-08: COGS overrides are now per-marketplace. The save is
      // scoped to the marketplace currently selected at the page header
      // (`mp`), so US-shipping uplifts etc. only affect the channel
      // they're entered for. The "all marketplaces" default override is
      // unaffected — it still applies wherever no marketplace-specific
      // row exists.
      const r = await api('/api/cairn/cogs-override/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ m_number: mNumber, cost_price_gbp: costPerUnit, marketplace: mp }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        alert(`Failed to save: ${j?.error || r.status}`)
      } else {
        // Absorb the saved value into the underlying data so the display
        // no longer depends on the pending-override state. Without this,
        // after the 2-second "saved" tick disappears the "save" link
        // reappears (because cogsOverrides[m_number] still has a value),
        // making it look like the save didn't take.
        setData(d => {
          if (!d) return d
          return {
            ...d,
            results: d.results.map(row =>
              row.m_number === mNumber ? recalcRow(row, costPerUnit) : row,
            ),
          }
        })
        setCogsOverrides(p => {
          const n = { ...p }
          delete n[mNumber]
          return n
        })
        setSavedCogs(p => ({ ...p, [mNumber]: true }))
        setTimeout(() => setSavedCogs(p => { const n = { ...p }; delete n[mNumber]; return n }), 2000)
      }
    } catch (e) {
      alert(`Save failed: ${e}`)
    } finally {
      setSavingCogs(p => { const n = { ...p }; delete n[mNumber]; return n })
    }
  }

  // Export the currently-visible rows (post-filter, post-sort, post-COGS-override)
  // as CSV. Respects everything the user is looking at on screen — if they
  // download with "Loss-makers only" + a search query, that's what they get.
  function downloadCsv() {
    const headers = [
      'Marketplace', 'ASIN', 'M Number', 'SKUs', 'Personalised', 'Blank',
      'Units', 'Avg Price', 'Gross Revenue', 'Net Revenue',
      'Fees per Unit', 'Fees Total', 'Fees Estimated', 'COGS per Unit', 'COGS Total',
      'Ad Spend',
      'Gross Profit', 'Gross Margin %',
      'Net Profit', 'Net Margin %',
      'Confidence', 'Cost Source', 'Fee Source', 'Composite Blank',
    ]

    const escape = (v: unknown): string => {
      if (v === null || v === undefined) return ''
      const s = typeof v === 'number' ? String(v) : String(v)
      // Quote if it contains comma, quote, newline, or leading/trailing whitespace
      if (/[,"\n\r]/.test(s) || s !== s.trim()) {
        return '"' + s.replace(/"/g, '""') + '"'
      }
      return s
    }

    const lines: string[] = [headers.map(escape).join(',')]
    for (const r of rows) {
      lines.push([
        r.marketplace,
        r.asin,
        r.m_number ?? '',
        (r.skus || []).join('; '),
        r.m_number && personalisedMNumbers.has(r.m_number) ? 'TRUE' : 'FALSE',
        r.blank_normalized ?? r.blank_raw ?? '',
        r.units,
        r.avg_price ?? '',
        r.gross_revenue.toFixed(2),
        r.net_revenue.toFixed(2),
        r.fees_per_unit !== null ? r.fees_per_unit.toFixed(2) : '',
        r.fees_total !== null ? r.fees_total.toFixed(2) : '',
        r.fees_estimated ? 'TRUE' : 'FALSE',
        r.cogs_per_unit !== null ? r.cogs_per_unit.toFixed(2) : '',
        r.cogs_total !== null ? r.cogs_total.toFixed(2) : '',
        r.ad_spend.toFixed(2),
        r.gross_profit !== null ? r.gross_profit.toFixed(2) : '',
        r.gross_margin_pct !== null ? r.gross_margin_pct.toFixed(2) : '',
        r.net_profit !== null ? r.net_profit.toFixed(2) : '',
        r.net_margin_pct !== null ? r.net_margin_pct.toFixed(2) : '',
        r.confidence,
        r.cost_source ?? '',
        r.fee_source ?? '',
        r.is_composite ? 'TRUE' : 'FALSE',
      ].map(escape).join(','))
    }

    // BOM so Excel opens UTF-8 cleanly without garbling £/€/etc.
    const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const today = new Date().toISOString().slice(0, 10)
    a.href = url
    a.download = `profitability-${mp}-${lookback}d-${today}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const costWarning = useMemo(() => {
    if (!data) return null
    const scored = data.results.filter(r => r.cogs_per_unit !== null)
    if (scored.length < 10) return null
    const uniq = new Set(scored.map(r => r.cogs_per_unit))
    if (uniq.size === 1) {
      const v = Array.from(uniq)[0]
      return `All ${scored.length} SKUs show identical COGS (${money(v, mp)}/unit). Blank costs haven\u2019t been populated — use the COGS column to override per SKU.`
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
          <p className="text-sm text-gray-500">
            Per-SKU margin. Edit COGS to see live impact on profit. Saved overrides persist.
          </p>
          <p className="text-xs text-gray-400 mt-1">
            All monetary values are in <strong>GBP</strong>, normalised by Cairn using daily FX rates so US / EU / CA / AU rows are directly comparable to UK. The marketplace selector below scopes which channel's orders to include — it doesn't change the display currency.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={downloadCsv}
            disabled={loading || rows.length === 0}
            title={rows.length === 0
              ? 'No rows to export — adjust filters or load data first'
              : `Download ${rows.length} row${rows.length === 1 ? '' : 's'} (respects current filter, sort, and any unsaved COGS overrides)`}
            className="text-sm px-3 py-1.5 border rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            ⬇ Download CSV {rows.length > 0 && <span className="text-gray-400">({rows.length})</span>}
          </button>
          <button onClick={load} className="text-sm px-3 py-1.5 border rounded hover:bg-gray-50">Refresh</button>
        </div>
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
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter ASIN, M# or blank…" className="flex-1 min-w-[140px] border rounded px-2 py-1 text-sm" />
        <label className="flex items-center gap-1 text-xs text-gray-600">
          <input type="checkbox" checked={onlyLoss} onChange={e => setOnlyLoss(e.target.checked)} /> Loss-makers only
        </label>
        <label className="flex items-center gap-1.5 text-xs text-gray-600" title={`${personalisedMNumbers.size} M-numbers currently flagged as personalised`}>
          Personalised
          <select
            value={personalisedFilter}
            onChange={e => setPersonalisedFilter(e.target.value as typeof personalisedFilter)}
            className="border rounded px-2 py-1 text-sm bg-white"
          >
            <option value="all">All</option>
            <option value="yes">Personalised only</option>
            <option value="no">Non-personalised only</option>
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-gray-600" title="Inclusive range. Leave a side blank for no bound. Type the number with or without the leading 'M'.">
          M#
          <input
            type="text"
            value={mFromStr}
            onChange={e => setMFromStr(e.target.value)}
            placeholder="from"
            className="border rounded px-2 py-1 w-20 text-sm font-mono"
            aria-label="M-number range from"
          />
          <span className="text-gray-400">–</span>
          <input
            type="text"
            value={mToStr}
            onChange={e => setMToStr(e.target.value)}
            placeholder="to"
            className="border rounded px-2 py-1 w-20 text-sm font-mono"
            aria-label="M-number range to"
          />
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

      {mp === 'ALL' && (
        <div className="mb-4 border border-blue-300 bg-blue-50 rounded-lg p-3 text-xs text-blue-900 space-y-1">
          <div>
            <span className="font-medium">Combined view:</span> totals sum across every Amazon marketplace (UK / DE / FR / IT / ES / NL / US / CA / AU). One row per ASIN per marketplace. COGS edits are read-only here — drill into a single marketplace to save changes.
          </div>
          <div className="text-blue-800">
            <span className="font-medium">EU note:</span> until multi-account ingestion lands, EU figures only reflect the NBNE seller account. NorthByNorthEast (Origin Crafts) orders are not yet included, so EU totals are an undercount.
          </div>
        </div>
      )}

      {partialErrors.length > 0 && (
        <div className="mb-4 border border-amber-300 bg-amber-50 rounded-lg p-3 text-xs text-amber-900">
          <span className="font-medium">Partial data: </span>
          failed to load {partialErrors.length} marketplace{partialErrors.length === 1 ? '' : 's'} —{' '}
          {partialErrors.map(e => `${e.marketplace} (${e.error})`).join(', ')}.
          Totals below exclude these.
        </div>
      )}

      {err && <div className="mb-4 border border-red-300 bg-red-50 rounded-lg p-3 text-sm text-red-900">{err}</div>}

      {/* Summary cards — recalculated live from overrides */}
      {s && (
        <>
          {/* Scope indicator — visible whenever filters narrow the summary */}
          {scopeLabel && (
            <div className="mb-2 text-xs text-gray-500">
              <span className="inline-flex items-center gap-1.5 bg-purple-50 border border-purple-200 text-purple-700 px-2 py-0.5 rounded">
                <span className="font-medium">Scope:</span>
                <span>{scopeLabel}</span>
                <span className="text-purple-400">· {s.total_skus} SKUs</span>
              </span>
              <span className="ml-2 text-gray-400">Tiles below reflect this group only.</span>
            </div>
          )}
          <div className="grid grid-cols-2 md:grid-cols-8 gap-3 mb-4">
            <Card label="Net revenue" value={money(s.total_net_revenue, mp)} />
            <Card label="Net profit" value={money(s.total_net_profit, mp)} cls={s.total_net_profit >= 0 ? 'text-green-700' : 'text-red-700'} />
            {/* Margin = aggregate Net profit / Net revenue across the
                current scope. Recomputed live from the (post-COGS-override)
                effective results, so it reflects what's on screen. */}
            <Card
              label="Margin"
              value={s.total_net_revenue > 0
                ? `${(100 * s.total_net_profit / s.total_net_revenue).toFixed(1)}%`
                : '—'}
              cls={s.total_net_revenue > 0 && s.total_net_profit >= 0 ? 'text-green-700' : s.total_net_revenue > 0 ? 'text-red-700' : 'text-gray-400'}
            />
            {/* Loss bleed = sum of negative net_profit only. Drag on the
                bottom line — actionable by retiring / re-pricing / cutting
                ads on the worst-performing SKUs. Headline-money tile
                even when zero, since "no bleed" is its own signal. */}
            <Card
              label="Loss bleed"
              value={money(s.total_loss_bleed, mp)}
              cls={s.total_loss_bleed < 0 ? 'text-red-700' : 'text-gray-400'}
            />
            <Card label="Healthy (≥20%)" value={String(b?.healthy ?? 0)} cls="text-green-700" />
            <Card label="Thin (5–20%)" value={String(b?.thin ?? 0)} cls="text-amber-600" />
            <Card label="Unprofitable" value={String(b?.unprofitable ?? 0)} cls="text-red-700" />
            <Card label="Unknown" value={String(b?.unknown ?? 0)} cls="text-gray-400" />
          </div>

          {/* Biggest Bleeders panel — surfaces the top-5 worst SKUs by
              absolute £ loss in the current scope. Click a row to drop
              the M-number into the search box so the table jumps to it. */}
          {s.top_loss_makers && s.top_loss_makers.length > 0 && (
            <div className="mb-4 bg-white border border-red-200 rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-red-50 border-b border-red-200 text-xs font-medium text-red-900 flex items-center justify-between">
                <span>Biggest bleeders {mp === 'ALL' ? '(across all channels)' : `(${mp})`}</span>
                <span className="text-red-700/70 font-normal">Click a row to filter the table to that M-number</span>
              </div>
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500 uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-1.5 text-left">MP</th>
                    <th className="px-3 py-1.5 text-left">ASIN</th>
                    <th className="px-3 py-1.5 text-left">M#</th>
                    <th className="px-3 py-1.5 text-right">Units</th>
                    <th className="px-3 py-1.5 text-right">Net rev</th>
                    <th className="px-3 py-1.5 text-right">Net loss</th>
                    <th className="px-3 py-1.5 text-right">Margin</th>
                    <th className="px-3 py-1.5 text-left">Conf.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {s.top_loss_makers.map(b => (
                    <tr
                      key={`${b.marketplace}-${b.asin}`}
                      className="hover:bg-red-50/40 cursor-pointer"
                      onClick={() => b.m_number && setQuery(b.m_number)}
                      title={b.m_number ? `Filter table to ${b.m_number}` : ''}
                    >
                      <td className="px-3 py-1.5 font-mono text-gray-600">{b.marketplace}</td>
                      <td className="px-3 py-1.5 font-mono">{b.asin}</td>
                      <td className="px-3 py-1.5 font-mono">{b.m_number ?? '—'}</td>
                      <td className="px-3 py-1.5 text-right">{b.units}</td>
                      <td className="px-3 py-1.5 text-right">{money(b.net_revenue, mp)}</td>
                      <td className="px-3 py-1.5 text-right text-red-700 font-medium">{money(b.net_profit, mp)}</td>
                      <td className="px-3 py-1.5 text-right text-red-700">{pct(b.net_margin_pct)}</td>
                      <td className="px-3 py-1.5 text-gray-500">{b.confidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* Table — `min-w-full` (not `w-full`) so the table can grow beyond
          the container's width and the parent div's overflow-x-auto
          actually triggers a horizontal scrollbar. With `w-full` the
          browser was squeezing columns to fit, hiding rightmost data. */}
      <div className="bg-white border rounded-lg overflow-x-auto">
        <table className="min-w-full w-auto text-sm">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
            <tr>
              {[
                { key: 'marketplace', label: 'MP' },
                { key: 'asin', label: 'ASIN' },
                { key: 'm_number', label: 'M#' },
                { key: 'sku', label: 'SKU' },
                { key: 'is_personalised', label: 'Pers.' },
                { key: 'blank_normalized', label: 'Blank' },
                { key: 'avg_price', label: 'Avg price', right: true },
                { key: 'units', label: 'Units', right: true },
                { key: 'net_revenue', label: 'Net rev', right: true },
                { key: 'fees_total', label: 'Fees', right: true },
                { key: 'cogs_per_unit', label: 'COGS/unit', right: true },
                { key: 'ad_spend', label: 'Ads', right: true },
                { key: 'net_profit', label: 'Net profit', right: true },
                { key: 'net_margin_pct', label: 'Margin', right: true },
              ].map(c => (
                <th key={c.key} onClick={() => headerClick(c.key)}
                  className={`px-2 py-1.5 cursor-pointer select-none whitespace-nowrap hover:bg-gray-100 ${c.right ? 'text-right' : 'text-left'}`}>
                  {c.label}
                  {sortKey === c.key && <span className="ml-1 text-gray-400">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && <tr><td colSpan={14} className="p-6 text-center text-gray-400">Loading…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={14} className="p-6 text-center text-gray-400">No rows.</td></tr>}
            {!loading && rows.map(r => {
              const isOverridden = r.m_number != null && r.m_number in cogsOverrides
              return (
                <tr key={`${r.asin}-${r.marketplace}`} className={`hover:bg-gray-50 ${r.confidence === 'LOW' ? 'text-gray-400' : ''} ${isOverridden ? 'bg-blue-50/50' : ''}`}>
                  {/* Marketplace — useful in single-mode for clarity, essential in combined mode */}
                  <td className="px-2 py-1.5 whitespace-nowrap text-xs text-gray-600 font-mono">{r.marketplace}</td>
                  {/* ASIN */}
                  <td className="px-2 py-1.5 whitespace-nowrap">{r.asin}</td>
                  {/* M# */}
                  <td className="px-2 py-1.5 whitespace-nowrap">{r.m_number ?? '—'}</td>
                  {/* SKU(s) — Cairn returns per-ASIN; the merchant SKUs are joined in
                      the Manufacture proxy from products.SKU. Multiple variants per
                      ASIN are common (regional / merchant) — show the first truncated
                      to 14 chars, surface the rest as "+N" with a hover tooltip
                      listing all. Capping the column width at ~14ch keeps the
                      14-column table readable on a 1080p screen. */}
                  <td
                    className="px-2 py-1.5 whitespace-nowrap font-mono text-xs max-w-[14ch] truncate"
                    title={(r.skus && r.skus.length > 0) ? r.skus.join(', ') : 'No SKU registered for this ASIN'}
                  >
                    {r.skus && r.skus.length > 0 ? (
                      <>
                        <span>{r.skus[0]}</span>
                        {r.skus.length > 1 && (
                          <span className="ml-1 text-gray-400">+{r.skus.length - 1}</span>
                        )}
                      </>
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>
                  {/* Personalised (Ivan #20) */}
                  <td className="px-2 py-1.5 whitespace-nowrap text-center" title={r.m_number && personalisedMNumbers.has(r.m_number) ? 'Personalised SKU' : ''}>
                    {r.m_number && personalisedMNumbers.has(r.m_number)
                      ? <span className="text-purple-600 font-semibold">●</span>
                      : <span className="text-gray-200">—</span>}
                  </td>
                  {/* Blank */}
                  <td className="px-2 py-1.5 whitespace-nowrap text-xs text-gray-500" title={r.blank_raw ?? ''}>
                    {r.blank_normalized ?? '—'}
                    {r.is_composite && <span className="ml-1 text-[9px] text-amber-600" title="Composite blank">◆</span>}
                  </td>
                  {/* Avg price (gross rev / units = what the customer pays inc VAT) */}
                  <td className="px-2 py-1.5 whitespace-nowrap text-right">{r.units > 0 ? money(r.gross_revenue / r.units, mp) : '—'}</td>
                  {/* Units */}
                  <td className="px-2 py-1.5 whitespace-nowrap text-right">{r.units}</td>
                  {/* Net rev */}
                  <td className="px-2 py-1.5 whitespace-nowrap text-right">{money(r.net_revenue, mp)}</td>
                  {/* Fees — italic + asterisk when filled by the
                      personalised fallback estimator (net rev × 25.5%)
                      so staff can see it's not a real SP-API number. */}
                  <td
                    className={`px-2 py-1.5 whitespace-nowrap text-right ${r.fees_estimated ? 'italic text-gray-500' : ''}`}
                    title={r.fees_estimated ? `Estimated at 25.5% of net revenue (no SP-API fee snapshot for this personalised SKU)` : ''}
                  >
                    {money(r.fees_total, mp)}{r.fees_estimated && <span className="text-amber-500 ml-0.5" aria-hidden="true">*</span>}
                  </td>
                  {/* COGS/unit — editable */}
                  <td className="px-2 py-1 whitespace-nowrap text-right">
                    <CogsCell
                      row={r}
                      mp={mp}
                      isCombined={mp === 'ALL'}
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
                  <td className="px-2 py-1.5 whitespace-nowrap text-right">{money(r.ad_spend, mp)}</td>
                  {/* Net profit */}
                  <td className="px-2 py-1.5 whitespace-nowrap text-right">
                    <span className={r.net_profit === null ? 'text-gray-400' : r.net_profit >= 0 ? 'text-green-700' : 'text-red-700'}>
                      {money(r.net_profit, mp)}
                    </span>
                  </td>
                  {/* Margin */}
                  <td className="px-2 py-1.5 whitespace-nowrap text-right">
                    <span className={r.net_margin_pct === null ? 'text-gray-400' : r.net_margin_pct >= 20 ? 'text-green-700 font-medium' : r.net_margin_pct >= 5 ? 'text-amber-600' : 'text-red-700 font-medium'}>
                      {pct(r.net_margin_pct)}
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
          {' · '}{data.marketplace === 'ALL' ? 'all channels combined' : data.marketplace}
          {' · '} last {data.lookback_days} days
          {Object.keys(cogsOverrides).length > 0 && (
            <span className="ml-2 text-blue-600">
              · {Object.keys(cogsOverrides).length} COGS override{Object.keys(cogsOverrides).length > 1 ? 's' : ''} applied
            </span>
          )}
        </p>
      )}
    </div>
  )
}

// ── COGS editable cell ───────────────────────────────────────────────────────

function CogsCell({ row, mp, isCombined, isOverridden, isSaving, isSaved, onOverride, onSave }: {
  row: MarginRow
  mp: string
  isCombined: boolean
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

  // In combined view, the cell is read-only — saving needs a single
  // marketplace target. Toby drills into one marketplace to edit.
  if (isCombined) {
    return (
      <span className="text-gray-700" title="Switch to a single marketplace to edit COGS">
        {money(displayVal, mp)}
      </span>
    )
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
          title={`Save as ${mp}-only override (other marketplaces keep their existing values).`}
        >
          save
        </button>
      )}
      {isSaving && <span className="text-[10px] text-gray-400">…</span>}
      {isSaved && <span className="text-[10px] text-green-600">✓</span>}
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
