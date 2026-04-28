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

interface GroupRow {
  label: string
  '7d': number
  '30d': number
  '90d': number
  all: number
  blank_names?: string
}

interface SkuRow extends GroupRow {
  type: string
  colour: string
  decoration: string
  theme: string
}

interface PersonalisedStats {
  windows: string[]
  totals: { '7d': number; '30d': number; '90d': number; all: number }
  by_type: GroupRow[]
  by_colour: GroupRow[]
  by_decoration: GroupRow[]
  by_theme: GroupRow[]
  by_sku: SkuRow[]
  catalogue_size: number
  last_order_date: string | null
}

type Tab = 'ready' | 'needs_making' | 'all'

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
// Personalised analytics panel
// ─────────────────────────────────────────────────────────────────────────────

type DimensionKey = 'by_type' | 'by_colour' | 'by_decoration' | 'by_theme' | 'by_sku'

const DIMENSION_LABELS: Record<DimensionKey, string> = {
  by_type: 'Blank type',
  by_colour: 'Colour',
  by_decoration: 'Decoration',
  by_theme: 'Theme',
  by_sku: 'By SKU',
}

function PersonalisedPanels() {
  const [stats, setStats] = useState<PersonalisedStats | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api('/api/d2c/personalised/stats/')
      .then(r => r.json())
      .then((d: PersonalisedStats) => { setStats(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])
  return (
    <>
      <PersonalisedAnalytics stats={stats} loading={loading} />
      <RegularStakeBlanks stats={stats} />
      <BrassCalculator stats={stats} />
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Regular Stake blank requirements
// Every Regular Stake memorial = 1 × Tom (acrylic stake) + 1 × Dick (aluminium
// face). Dicks come in Silver, Gold, Copper (and occasionally Black/Stone as
// outliers). This panel splits the weekly Regular Stake volume into Tom and
// per-colour Dick blank requirements, so Ben + Ivan know what to cut.
// ─────────────────────────────────────────────────────────────────────────────

const DICK_PRIMARY_COLOURS = ['Silver', 'Gold', 'Copper']
// Buffer for both blank types
const BLANK_BUFFER = 1.2

// Aluminium sublimation material (for Dick faces)
// Supplier: Novachrome — 610 × 305 mm sheet, £2.77 ex VAT per sheet, 12 Dicks per sheet.
// Adhesive backing: 600 mm × 1000 m roll @ £650 ex VAT  → £1.083 / m² → ~£0.017 / Dick.
const ALU_SHEET_DICKS = 12
const ALU_SHEET_COST_GBP = 2.77
const ADHESIVE_COST_PER_DICK_GBP = 0.017 // (610×305 / 12) mm² × £650 / 600,000,000 mm²

function RegularStakeBlanks({ stats }: { stats: PersonalisedStats | null }) {
  const [open, setOpen] = useState(true)

  // Filter by_sku to Regular Stakes only, then group by colour
  const rs = (stats?.by_sku || []).filter(r => r.type === 'Regular Stake')

  const colourTotals = rs.reduce<Record<string, { d7: number; d30: number; d90: number; all: number }>>(
    (acc, r) => {
      const key = r.colour || '(unspecified)'
      if (!acc[key]) acc[key] = { d7: 0, d30: 0, d90: 0, all: 0 }
      acc[key].d7 += r['7d']
      acc[key].d30 += r['30d']
      acc[key].d90 += r['90d']
      acc[key].all += r.all
      return acc
    },
    {},
  )

  const total30d = Object.values(colourTotals).reduce((s, v) => s + v.d30, 0)
  const totalWeekly = Math.ceil(total30d / 4.3)
  const totalRecommended = Math.ceil(totalWeekly * BLANK_BUFFER)

  // Sort by 30d desc, primary colours first
  const sortedColours = Object.keys(colourTotals).sort((a, b) => {
    const ap = DICK_PRIMARY_COLOURS.indexOf(a)
    const bp = DICK_PRIMARY_COLOURS.indexOf(b)
    if (ap !== -1 && bp === -1) return -1
    if (bp !== -1 && ap === -1) return 1
    if (ap !== -1 && bp !== -1) return ap - bp
    return colourTotals[b].d30 - colourTotals[a].d30
  })

  return (
    <section className="bg-white rounded-lg border border-slate-200 mt-6">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <IconChevron open={open} />
          <h3 className="text-sm font-semibold text-slate-900">Regular Stake blanks — Tom + Dick</h3>
          <span className="text-xs text-slate-500">
            · 1 Tom (acrylic) + 1 Dick (aluminium) per order
          </span>
        </div>
        <span className="text-xs text-slate-400">Per-colour cut schedule for Ben &amp; Ivan</span>
      </button>

      {open && (
        <div className="px-5 pb-5">
          {total30d === 0 ? (
            <p className="text-sm text-slate-400">No Regular Stake orders recorded in the window.</p>
          ) : (
            <>
              {/* Tom total + Dick colour grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div className="bg-sky-50 border border-sky-200 rounded p-3">
                  <p className="text-xs text-sky-800 uppercase tracking-wide font-medium">Tom · acrylic stake</p>
                  <p className="text-3xl font-semibold text-sky-900 mt-1">{totalRecommended}</p>
                  <p className="text-xs text-sky-700 mt-1">
                    per week ({totalWeekly} avg + 20% buffer)
                  </p>
                </div>
                <div className="bg-amber-50 border border-amber-200 rounded p-3">
                  <p className="text-xs text-amber-800 uppercase tracking-wide font-medium">Dick · aluminium face</p>
                  <p className="text-3xl font-semibold text-amber-900 mt-1">{totalRecommended}</p>
                  <p className="text-xs text-amber-700 mt-1">
                    per week — split by colour below
                  </p>
                </div>
              </div>

              {/* Colour breakdown table */}
              <div className="overflow-x-auto border border-slate-200 rounded">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 border-b border-slate-200 text-xs text-slate-600 uppercase tracking-wide">
                    <tr>
                      <th className="text-left px-3 py-2 font-semibold">Dick colour</th>
                      <th className="text-right px-3 py-2 font-semibold">7d</th>
                      <th className="text-right px-3 py-2 font-semibold">30d</th>
                      <th className="text-right px-3 py-2 font-semibold">90d</th>
                      <th className="text-right px-3 py-2 font-semibold bg-emerald-50">Weekly</th>
                      <th className="text-right px-3 py-2 font-semibold bg-emerald-50">Cut / wk</th>
                      <th className="text-right px-3 py-2 font-semibold bg-amber-50" title="Aluminium sheets to cut per week (12 Dicks per 610 × 305 mm sheet)">Sheets / wk</th>
                      <th className="text-right px-3 py-2 font-semibold">% mix</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedColours.map(col => {
                      const v = colourTotals[col]
                      const wk = Math.ceil(v.d30 / 4.3)
                      const cut = v.d30 > 0 ? Math.ceil(wk * BLANK_BUFFER) : 0
                      const sheetsDecimal = cut / ALU_SHEET_DICKS
                      const sheets = Math.ceil(sheetsDecimal)
                      const pct = total30d > 0 ? (v.d30 / total30d * 100) : 0
                      const isPrimary = DICK_PRIMARY_COLOURS.includes(col)
                      return (
                        <tr key={col} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                          <td className="px-3 py-2 font-medium text-slate-800">
                            {col}
                            {!isPrimary && (
                              <span className="ml-2 text-xs text-amber-700 bg-amber-100 border border-amber-200 px-1.5 py-0.5 rounded">
                                non-standard
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">{v.d7}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{v.d30}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{v.d90}</td>
                          <td className="px-3 py-2 text-right tabular-nums bg-emerald-50 text-emerald-900">{wk}</td>
                          <td className="px-3 py-2 text-right tabular-nums bg-emerald-50 text-emerald-900 font-semibold">{cut}</td>
                          <td className="px-3 py-2 text-right tabular-nums bg-amber-50 text-amber-900 font-semibold"
                              title={`${cut} Dicks ÷ ${ALU_SHEET_DICKS} per sheet = ${sheetsDecimal.toFixed(1)}`}>
                            {cut > 0 ? sheets : '—'}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-slate-500">{pct.toFixed(1)}%</td>
                        </tr>
                      )
                    })}
                  </tbody>
                  <tfoot>
                    {(() => {
                      const totalSheetsCeilSum = sortedColours.reduce((s, c) => {
                        const v = colourTotals[c]
                        const wk = Math.ceil(v.d30 / 4.3)
                        const cut = v.d30 > 0 ? Math.ceil(wk * BLANK_BUFFER) : 0
                        return s + Math.ceil(cut / ALU_SHEET_DICKS)
                      }, 0)
                      const aluCost = totalSheetsCeilSum * ALU_SHEET_COST_GBP
                      const adhCost = totalRecommended * ADHESIVE_COST_PER_DICK_GBP
                      return (
                        <>
                          <tr className="border-t-2 border-slate-300 bg-slate-50">
                            <td className="px-3 py-2 font-semibold text-slate-800">Total</td>
                            <td className="px-3 py-2 text-right tabular-nums font-semibold">{Object.values(colourTotals).reduce((s, v) => s + v.d7, 0)}</td>
                            <td className="px-3 py-2 text-right tabular-nums font-semibold">{total30d}</td>
                            <td className="px-3 py-2 text-right tabular-nums font-semibold">{Object.values(colourTotals).reduce((s, v) => s + v.d90, 0)}</td>
                            <td className="px-3 py-2 text-right tabular-nums bg-emerald-50 text-emerald-900 font-semibold">{totalWeekly}</td>
                            <td className="px-3 py-2 text-right tabular-nums bg-emerald-50 text-emerald-900 font-bold">{totalRecommended}</td>
                            <td className="px-3 py-2 text-right tabular-nums bg-amber-50 text-amber-900 font-bold">{totalSheetsCeilSum}</td>
                            <td className="px-3 py-2 text-right tabular-nums text-slate-500">100%</td>
                          </tr>
                          <tr>
                            <td className="px-3 py-2 text-xs text-slate-500" colSpan={6}>
                              Weekly material cost (aluminium + adhesive, ex VAT)
                            </td>
                            <td className="px-3 py-2 text-right text-xs font-semibold text-amber-900 bg-amber-50">
                              £{(aluCost + adhCost).toFixed(2)}
                            </td>
                            <td className="px-3 py-2 text-right text-xs text-slate-500" title={`Aluminium: £${aluCost.toFixed(2)} · Adhesive: £${adhCost.toFixed(2)}`}>
                              alu £{aluCost.toFixed(2)} · adh £{adhCost.toFixed(2)}
                            </td>
                          </tr>
                        </>
                      )
                    })()}
                  </tfoot>
                </table>
              </div>
              <p className="text-xs text-slate-400 mt-2">
                Each Regular Stake order consumes <span className="font-medium">1 Tom acrylic stake</span> and
                <span className="font-medium"> 1 Dick aluminium face</span> in the ordered colour.
                Colours outside Silver / Gold / Copper are flagged as non-standard.
                {' '}
                Aluminium sublimation sheet (Novachrome, 610 × 305 mm) = 12 Dicks per sheet
                @ £{ALU_SHEET_COST_GBP.toFixed(2)} ex VAT.
                Adhesive backing ≈ £{ADHESIVE_COST_PER_DICK_GBP.toFixed(3)} per Dick
                (600 mm × 1 km roll @ £650).
              </p>
            </>
          )}
        </div>
      )}
    </section>
  )
}

type BlankScope =
  | { kind: 'type'; productType: string }
  | { kind: 'colour'; colour: string }

function BlankNameCell({
  scope,
  value,
  onSaved,
}: {
  scope: BlankScope
  value: string
  onSaved: (newValue: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value || '')
  const [saving, setSaving] = useState(false)

  useEffect(() => { setDraft(value || '') }, [value])

  const save = async () => {
    setSaving(true)
    try {
      const url = scope.kind === 'type'
        ? '/api/d2c/personalised/blanks/'
        : '/api/d2c/personalised/colour-blanks/'
      const body = scope.kind === 'type'
        ? { product_type: scope.productType, blank_names: draft }
        : { colour: scope.colour, blank_names: draft }
      const res = await api(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) {
        onSaved(draft)
        setEditing(false)
      }
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <div className="flex items-center gap-1">
        <input
          type="text"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') save()
            else if (e.key === 'Escape') { setDraft(value || ''); setEditing(false) }
          }}
          autoFocus
          placeholder="e.g. Tom (acrylic), Dick (aluminium)"
          className="border border-slate-300 rounded px-1.5 py-0.5 text-xs w-56"
        />
        <button
          onClick={save}
          disabled={saving}
          className="bg-slate-800 text-white px-2 py-0.5 rounded text-xs hover:bg-slate-900 disabled:opacity-50"
        >
          {saving ? '…' : 'Save'}
        </button>
        <button
          onClick={() => { setDraft(value || ''); setEditing(false) }}
          className="text-slate-400 hover:text-slate-700 text-xs"
        >
          ✕
        </button>
      </div>
    )
  }

  if (value) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="text-left text-xs text-slate-700 hover:text-slate-900 hover:underline"
        title="Click to edit"
      >
        {value}
      </button>
    )
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className="text-xs text-blue-700 hover:text-blue-900 italic"
    >
      + name blank
    </button>
  )
}

function PersonalisedAnalytics({ stats, loading }: { stats: PersonalisedStats | null; loading: boolean }) {
  const [dimension, setDimension] = useState<DimensionKey>('by_type')
  const [open, setOpen] = useState(true)
  // Local override of blank_names on by_type rows after inline edit — saves a
  // round-trip to re-fetch stats just to update one cell.
  const [blankOverrides, setBlankOverrides] = useState<Record<string, string>>({})

  const rows = stats ? stats[dimension] : []

  return (
    <section className="bg-white rounded-lg border border-slate-200 mt-6">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <IconChevron open={open} />
          <h3 className="text-sm font-semibold text-slate-900">Personalised order analytics</h3>
          {stats && (
            <span className="text-xs text-slate-500">
              · {stats.catalogue_size} SKUs · {stats.totals.all.toLocaleString()} orders all-time
            </span>
          )}
        </div>
        <span className="text-xs text-slate-400">For Ivan &amp; Ben — plan blank batches</span>
      </button>

      {open && (
        <div className="px-5 pb-5">
          {loading ? (
            <p className="text-sm text-slate-400">Loading…</p>
          ) : !stats ? (
            <p className="text-sm text-rose-700">Couldn&apos;t load personalised stats.</p>
          ) : (
            <>
              {/* Totals row */}
              <div className="grid grid-cols-4 gap-3 mb-4">
                {(['7d', '30d', '90d', 'all'] as const).map(w => (
                  <div key={w} className="bg-slate-50 border border-slate-200 rounded px-3 py-2">
                    <p className="text-xs text-slate-500 uppercase tracking-wide">{w === 'all' ? 'All-time' : `Last ${w}`}</p>
                    <p className="text-xl font-semibold text-slate-900">{stats.totals[w].toLocaleString()}</p>
                  </div>
                ))}
              </div>

              {/* Dimension tabs */}
              <div className="flex items-center gap-1 mb-3 border-b border-slate-200">
                {(Object.keys(DIMENSION_LABELS) as DimensionKey[]).map(k => (
                  <button
                    key={k}
                    onClick={() => setDimension(k)}
                    className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
                      dimension === k
                        ? 'border-slate-900 text-slate-900'
                        : 'border-transparent text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    {DIMENSION_LABELS[k]}
                  </button>
                ))}
              </div>

              {/* Table */}
              <div className="overflow-x-auto max-h-96 border border-slate-200 rounded">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 border-b border-slate-200 text-xs text-slate-600 uppercase tracking-wide sticky top-0">
                    <tr>
                      <th className="text-left px-3 py-2 font-semibold">
                        {dimension === 'by_sku' ? 'SKU' : DIMENSION_LABELS[dimension]}
                      </th>
                      {(dimension === 'by_type' || dimension === 'by_colour') && (
                        <th className="text-left px-3 py-2 font-semibold">Blanks</th>
                      )}
                      {dimension === 'by_sku' && (
                        <>
                          <th className="text-left px-2 py-2 font-semibold">Type</th>
                          <th className="text-left px-2 py-2 font-semibold">Colour</th>
                          <th className="text-left px-2 py-2 font-semibold">Decoration</th>
                          <th className="text-left px-2 py-2 font-semibold">Theme</th>
                        </>
                      )}
                      <th className="text-right px-3 py-2 font-semibold">7d</th>
                      <th className="text-right px-3 py-2 font-semibold">30d</th>
                      <th className="text-right px-3 py-2 font-semibold">90d</th>
                      <th className="text-right px-3 py-2 font-semibold">All-time</th>
                      <th className="text-right px-3 py-2 font-semibold bg-emerald-50" title="30d ÷ 4.3 (average sales per week)">Weekly</th>
                      <th className="text-right px-3 py-2 font-semibold bg-emerald-50" title="Weekly rate rounded up, +20% buffer — suggested batch size for Ben & Ivan">Make / wk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.length === 0 ? (
                      <tr>
                        <td colSpan={
                          dimension === 'by_sku' ? 11
                          : (dimension === 'by_type' || dimension === 'by_colour') ? 8
                          : 7
                        }
                            className="px-3 py-4 text-center text-slate-400 text-xs">
                          No personalised orders recorded yet.
                        </td>
                      </tr>
                    ) : (
                      rows.map((r, i) => {
                        const weekly = Math.round(r['30d'] / 4.3 * 10) / 10
                        const suggested = r['30d'] > 0 ? Math.ceil(Math.ceil(r['30d'] / 4.3) * 1.2) : 0
                        return (
                        <tr key={i} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                          <td className="px-3 py-2 font-medium text-slate-800">
                            {dimension === 'by_sku' ? (
                              <span className="font-mono text-xs">{r.label}</span>
                            ) : (r.label || '—')}
                          </td>
                          {dimension === 'by_type' && (
                            <td className="px-3 py-2">
                              <BlankNameCell
                                scope={{ kind: 'type', productType: r.label }}
                                value={blankOverrides[`type:${r.label}`] ?? r.blank_names ?? ''}
                                onSaved={v => setBlankOverrides(prev => ({ ...prev, [`type:${r.label}`]: v }))}
                              />
                            </td>
                          )}
                          {dimension === 'by_colour' && (
                            <td className="px-3 py-2">
                              <BlankNameCell
                                scope={{ kind: 'colour', colour: r.label }}
                                value={blankOverrides[`colour:${r.label}`] ?? r.blank_names ?? ''}
                                onSaved={v => setBlankOverrides(prev => ({ ...prev, [`colour:${r.label}`]: v }))}
                              />
                            </td>
                          )}
                          {dimension === 'by_sku' && 'type' in r && (
                            <>
                              <td className="px-2 py-2 text-slate-600 text-xs">{(r as SkuRow).type || '—'}</td>
                              <td className="px-2 py-2 text-slate-600 text-xs">{(r as SkuRow).colour || '—'}</td>
                              <td className="px-2 py-2 text-slate-600 text-xs">{(r as SkuRow).decoration || '—'}</td>
                              <td className="px-2 py-2 text-slate-600 text-xs">{(r as SkuRow).theme || '—'}</td>
                            </>
                          )}
                          <td className="px-3 py-2 text-right tabular-nums">{r['7d']}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{r['30d']}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{r['90d']}</td>
                          <td className="px-3 py-2 text-right tabular-nums font-semibold">{r.all}</td>
                          <td className="px-3 py-2 text-right tabular-nums bg-emerald-50 text-emerald-900">{weekly || '—'}</td>
                          <td className="px-3 py-2 text-right tabular-nums bg-emerald-50 text-emerald-900 font-semibold">{suggested || '—'}</td>
                        </tr>
                        )
                      })
                    )}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-slate-400 mt-2">
                <span className="font-medium">Weekly</span> = 30-day qty ÷ 4.3 (trailing weekly average).
                <span className="font-medium ml-2">Make / wk</span> = weekly rate rounded up, +20% buffer — the recommended batch size for Ben &amp; Ivan to keep D2C supplied.
              </p>
            </>
          )}
        </div>
      )}
    </section>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Brass sheet calculator (cost, yield, weekly consumption)
// ─────────────────────────────────────────────────────────────────────────────

// Brass sheet is 2 mm × 1000 mm × 600 mm and costs ~£240 inc VAT & delivery.
// Plaque sizes, in mm (converted from inches):
//   Small  3" × 1.5"   ≈  76 × 38
//   Medium 4" × 2"     ≈ 102 × 51
//   Large  5" × 3"     ≈ 127 × 76
//   XL     6" × 4"     ≈ 152 × 102
// Yield per sheet via nested rectangular packing on 1000 × 600 mm.
const BRASS_SHEET_COST_GBP = 240
const BRASS_SHEET_MM = { length: 1000, width: 600 }

function packYield(plaqueL: number, plaqueW: number): number {
  // Try both orientations (L×W and W×L) and take whichever fits more plaques.
  const a = Math.floor(BRASS_SHEET_MM.length / plaqueL) * Math.floor(BRASS_SHEET_MM.width / plaqueW)
  const b = Math.floor(BRASS_SHEET_MM.length / plaqueW) * Math.floor(BRASS_SHEET_MM.width / plaqueL)
  return Math.max(a, b)
}

interface BrassSizeSpec {
  label: string           // e.g. "Large"
  inchDesc: string        // "5\" × 3\""
  mmL: number
  mmW: number
  typeLabel: string       // matches PersonalisedSKU.product_type we assign
}

const BRASS_SIZES: BrassSizeSpec[] = [
  { label: 'Small',  inchDesc: '3" × 1.5"', mmL: 76,  mmW: 38,  typeLabel: 'Small Brass' },
  { label: 'Medium', inchDesc: '4" × 2"',   mmL: 102, mmW: 51,  typeLabel: 'Medium Brass' },
  { label: 'Large',  inchDesc: '5" × 3"',   mmL: 127, mmW: 76,  typeLabel: 'Large Brass' },
  { label: 'XL',     inchDesc: '6" × 4"',   mmL: 152, mmW: 102, typeLabel: 'XL Brass' },
]

function BrassCalculator({ stats }: { stats: PersonalisedStats | null }) {
  const [open, setOpen] = useState(true)

  const weeklyFor = (typeLabel: string): number => {
    if (!stats) return 0
    const row = stats.by_type.find(r => r.label === typeLabel)
    if (!row) return 0
    return Math.ceil(row['30d'] / 4.3)
  }

  const rows = BRASS_SIZES.map(spec => {
    const y = packYield(spec.mmL, spec.mmW)
    const costEach = BRASS_SHEET_COST_GBP / y
    const weekly = weeklyFor(spec.typeLabel)
    const recommended = weekly > 0 ? Math.ceil(weekly * 1.2) : 0
    const sheetsPerWeek = recommended > 0 ? Math.ceil(recommended / y * 10) / 10 : 0
    return { spec, yield_: y, costEach, weekly, recommended, sheetsPerWeek }
  })

  const totalWeeklyPlaques = rows.reduce((s, r) => s + r.recommended, 0)
  const totalSheetsPerWeek = rows.reduce((s, r) => s + r.sheetsPerWeek, 0)
  const weeklySpend = totalSheetsPerWeek * BRASS_SHEET_COST_GBP

  return (
    <section className="bg-white rounded-lg border border-slate-200 mt-6">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <IconChevron open={open} />
          <h3 className="text-sm font-semibold text-slate-900">Brass plaque production</h3>
          <span className="text-xs text-slate-500">
            · sheet 1000 × 600 × 2 mm · £{BRASS_SHEET_COST_GBP} inc VAT
          </span>
        </div>
        <span className="text-xs text-slate-400">Yield + weekly cadence</span>
      </button>

      {open && (
        <div className="px-5 pb-5">
          <div className="overflow-x-auto border border-slate-200 rounded">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs text-slate-600 uppercase tracking-wide">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold">Size</th>
                  <th className="text-left px-3 py-2 font-semibold">Dimensions</th>
                  <th className="text-right px-3 py-2 font-semibold" title="Plaques per 1000 × 600 mm sheet">Plaques / sheet</th>
                  <th className="text-right px-3 py-2 font-semibold" title="£240 / yield">£ / plaque</th>
                  <th className="text-right px-3 py-2 font-semibold">30d orders</th>
                  <th className="text-right px-3 py-2 font-semibold bg-emerald-50">Weekly rate</th>
                  <th className="text-right px-3 py-2 font-semibold bg-emerald-50">Make / wk</th>
                  <th className="text-right px-3 py-2 font-semibold bg-amber-50">Sheets / wk</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const row30d = stats?.by_type.find(t => t.label === r.spec.typeLabel)
                  return (
                    <tr key={r.spec.label} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                      <td className="px-3 py-2 font-medium text-slate-800">{r.spec.label}</td>
                      <td className="px-3 py-2 text-slate-600 text-xs">{r.spec.inchDesc} ({r.spec.mmL}×{r.spec.mmW} mm)</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.yield_}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-700">£{r.costEach.toFixed(2)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row30d?.['30d'] ?? 0}</td>
                      <td className="px-3 py-2 text-right tabular-nums bg-emerald-50 text-emerald-900">{r.weekly || '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums bg-emerald-50 text-emerald-900 font-semibold">{r.recommended || '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums bg-amber-50 text-amber-900">{r.sheetsPerWeek.toFixed(1)}</td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-300 bg-slate-50">
                  <td className="px-3 py-2 font-semibold text-slate-800" colSpan={5}>Totals (recommended weekly)</td>
                  <td className="px-3 py-2 text-right"></td>
                  <td className="px-3 py-2 text-right tabular-nums font-bold text-emerald-900 bg-emerald-50">
                    {totalWeeklyPlaques} plaques
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-bold text-amber-900 bg-amber-50">
                    {totalSheetsPerWeek.toFixed(1)} sheets
                  </td>
                </tr>
                <tr>
                  <td className="px-3 py-2 text-xs text-slate-500" colSpan={7}>Weekly brass spend at current demand</td>
                  <td className="px-3 py-2 text-right text-xs font-semibold text-slate-700 bg-amber-50">£{weeklySpend.toFixed(0)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="text-xs text-slate-400 mt-2">
            <span className="font-medium">Plaques / sheet</span> uses the best of two packing orientations
            (no kerf / spacing allowance). Add a ~5% cut-waste margin when ordering.
            <span className="font-medium ml-2">Make / wk</span> = weekly rate +20% buffer.
          </p>
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
  const [tab, setTab] = useState<Tab>('ready')
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [fulfilling, setFulfilling] = useState<Set<number>>(new Set())
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkDispatching, setBulkDispatching] = useState(false)

  // Debounce search input → active search term (250ms)
  useEffect(() => {
    const h = setTimeout(() => setSearch(searchInput.trim()), 250)
    return () => clearTimeout(h)
  }, [searchInput])

  const loadOrders = useCallback(() => {
    const params = new URLSearchParams({ page_size: '500' })
    if (search) {
      params.set('search', search)
      // When searching, widen the net to include dispatched orders too so
      // users can look up historical shipments by SKU / order-id / keyword.
      // (Status filter is ignored during search — intent is "find anywhere".)
    } else if (tab === 'all') {
      // All tab: explicit "all_incl_dispatched" → fetch everything. Otherwise
      // an empty default or any specific status filter goes through the
      // status filtering below.
      if (statusFilter === 'all_incl_dispatched') {
        // no filter — fetch every status
      } else if (statusFilter) {
        params.set('status', statusFilter)
      } else {
        // Default: hide dispatched so old orders don't clutter the view.
        params.set('status__in', 'pending,in_progress,made')
      }
    } else {
      // Ready / Needs making: only ever active orders.
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
  }, [tab, statusFilter, search])

  useEffect(() => { loadOrders() }, [loadOrders])

  // Reset selection when the visible set changes (tab / search / status filter)
  useEffect(() => { setSelected(new Set()) }, [tab, search, statusFilter])

  const flash = (msg: string) => {
    setMessage(msg)
    setTimeout(() => setMessage(''), 3000)
  }

  // Active = anything that still needs human attention.
  // Once an order is dispatched (or cancelled) it falls out of every count
  // and every tab list — it remains in the DB and the analytics, but Jo
  // sees a clean slate. Set the status filter to "Dispatched" or
  // "All statuses" on the All tab to bring historic rows back into view.
  const activeOrders = orders.filter(
    o => o.status !== 'dispatched' && o.status !== 'cancelled',
  )
  const nonPersonalised = activeOrders.filter(o => !o.product_is_personalised)

  const filteredOrders = (() => {
    if (tab === 'ready') {
      return nonPersonalised.filter(o =>
        o.status === 'made' || (o.status !== 'made' && o.can_fulfil_from_stock)
      )
    }
    if (tab === 'needs_making') {
      return nonPersonalised.filter(o =>
        o.status !== 'made' && !o.can_fulfil_from_stock
      )
    }
    // All tab — when the user explicitly chose a status (or "all_incl"),
    // honour that and show whatever the API returned. Otherwise default to
    // active orders only.
    if (statusFilter === '' || statusFilter === undefined) {
      return activeOrders
    }
    return orders
  })()

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

  // Mark every personalised pending order as sent. Backend mark_dispatched is
  // a no-op on stock for personalised products (product.is_personalised guard
  // in mark_dispatched), so this is a pure status flip — safe to bulk-apply.
  const markAllPersonalisedSent = async () => {
    const targets = orders.filter(
      o => o.product_is_personalised && o.status !== 'dispatched' && o.status !== 'cancelled',
    )
    if (targets.length === 0) return
    if (!confirm(`Mark ${targets.length} personalised order(s) as sent?`)) return
    const ids = targets.map(o => o.id)
    setFulfilling(new Set(ids))
    try {
      // Loop sequentially — the bulk-fulfil endpoint refuses personalised
      // orders by design (different semantics), so we hit mark_dispatched
      // per row. Cheap enough at typical batch sizes (<100).
      let ok = 0
      for (const id of ids) {
        const resp = await api(`/api/dispatch/${id}/mark-dispatched/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        })
        if (resp.ok) ok++
      }
      flash(`Marked ${ok} of ${ids.length} personalised order(s) as sent`)
      loadOrders()
    } finally {
      setFulfilling(new Set())
    }
  }

  // Selection helpers
  const toggleSelect = (id: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const visibleIds = filteredOrders.map(o => o.id)
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every(id => selected.has(id))
  const someVisibleSelected = visibleIds.some(id => selected.has(id)) && !allVisibleSelected

  const toggleSelectAll = () => {
    setSelected(prev => {
      if (allVisibleSelected) {
        // Deselect all visible
        const next = new Set(prev)
        for (const id of visibleIds) next.delete(id)
        return next
      }
      // Select all visible
      const next = new Set(prev)
      for (const id of visibleIds) next.add(id)
      return next
    })
  }

  // Dispatch the selected orders (reuses bulk-fulfil which handles
  // pending + made → dispatched with atomic stock deduction).
  const bulkDispatchSelected = async () => {
    const ids = Array.from(selected)
    if (ids.length === 0) return
    setBulkDispatching(true)
    try {
      const resp = await api('/api/dispatch/bulk-fulfil/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      })
      if (resp.ok) {
        const data = await resp.json()
        flash(
          `Dispatched ${data.fulfilled.length} order(s)` +
          (data.failed.length ? ` · ${data.failed.length} failed (${data.failed[0]?.reason || ''})` : '')
        )
        setSelected(new Set())
        loadOrders()
      } else {
        const err = await resp.json().catch(() => ({}))
        flash(err.error || 'Bulk dispatch failed')
      }
    } finally {
      setBulkDispatching(false)
    }
  }

  const markMade = async (id: number) => {
    setFulfilling(prev => new Set(prev).add(id))
    try {
      const resp = await api(`/api/dispatch/${id}/mark-made/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (resp.ok) {
        flash('Marked as made')
        loadOrders()
      } else {
        const err = await resp.json().catch(() => ({}))
        flash(err.error || `Failed to mark made (HTTP ${resp.status})`)
      }
    } catch (e) {
      flash('Network error — try again')
      console.error('markMade failed', e)
    } finally {
      setFulfilling(prev => { const s = new Set(prev); s.delete(id); return s })
    }
  }

  const markDispatched = async (id: number) => {
    setFulfilling(prev => new Set(prev).add(id))
    try {
      const resp = await api(`/api/dispatch/${id}/mark-dispatched/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (resp.ok) {
        flash('Marked as dispatched')
        loadOrders()
      } else {
        const err = await resp.json().catch(() => ({}))
        flash(err.error || `Failed to dispatch (HTTP ${resp.status})`)
      }
    } catch (e) {
      flash('Network error — try again')
      console.error('markDispatched failed', e)
    } finally {
      setFulfilling(prev => { const s = new Set(prev); s.delete(id); return s })
    }
  }

  const formatDate = (d: string | null) => {
    if (!d) return ''
    return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  }

  const readyCount = nonPersonalised.filter(o =>
    o.status === 'made' || (o.status !== 'made' && o.can_fulfil_from_stock)
  ).length
  const needsMakingCount = nonPersonalised.filter(o =>
    o.status !== 'made' && !o.can_fulfil_from_stock
  ).length

  // All-tab count reflects whatever set is currently visible (depends on the
  // status filter dropdown). Defaults to active orders so a fresh page load
  // doesn't include yesterday's dispatched.
  const allTabCount = (statusFilter === '' || statusFilter === undefined)
    ? activeOrders.length
    : orders.length

  const TABS: { key: Tab; label: string; count: number }[] = [
    { key: 'ready', label: 'Ready to ship', count: readyCount },
    { key: 'needs_making', label: 'Needs making', count: needsMakingCount },
    { key: 'all', label: 'All', count: allTabCount },
  ]

  const renderOrderCard = (order: DispatchOrder) => (
    <div
      key={order.id}
      className={`bg-white rounded-md border p-3 transition-colors ${
        selected.has(order.id) ? 'border-slate-900 bg-slate-50' : 'border-slate-200'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2.5 flex-wrap">
          <input
            type="checkbox"
            checked={selected.has(order.id)}
            onChange={() => toggleSelect(order.id)}
            aria-label={`Select ${order.order_id}`}
            className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
          />
          <span className="font-mono text-sm text-slate-700">{order.order_id}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_COLOURS[order.status]}`}>
            {order.status.replace('_', ' ')}
          </span>
          {order.flags && (
            <span className="text-xs bg-orange-50 text-orange-800 border border-orange-200 px-1.5 py-0.5 rounded">
              {order.flags}
            </span>
          )}
          {order.product_is_personalised && (
            <span
              className="text-xs bg-violet-50 text-violet-800 border border-violet-200 px-1.5 py-0.5 rounded font-semibold"
              title="Personalised — handled in memorial app / Zenstores. Counted in analytics below."
            >
              Personalised
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
            <>
              <button
                onClick={() => markMade(order.id)}
                disabled={fulfilling.has(order.id)}
                className="bg-slate-800 text-white px-3 py-1 rounded text-xs hover:bg-slate-900 disabled:opacity-50"
                title="Mark produced — moves to Ready to ship"
              >
                {fulfilling.has(order.id) ? '…' : 'Mark made'}
              </button>
              <button
                onClick={() => markDispatched(order.id)}
                disabled={fulfilling.has(order.id)}
                className="bg-blue-700 text-white px-3 py-1 rounded text-xs hover:bg-blue-800 disabled:opacity-50"
                title="Mark dispatched — skips made, deducts stock if any is available"
              >
                {fulfilling.has(order.id) ? '…' : 'Dispatch'}
              </button>
            </>
          )}
          {order.status === 'made' && (
            <button
              onClick={() => markDispatched(order.id)}
              disabled={fulfilling.has(order.id)}
              className="bg-blue-700 text-white px-3 py-1 rounded text-xs hover:bg-blue-800 disabled:opacity-50"
            >
              {fulfilling.has(order.id) ? 'Dispatching…' : 'Mark dispatched'}
            </button>
          )}
          {/* Personalised orders ship from the memorial app / Zenstores; the
              d2c app never gets a shipment signal back. "Mark sent" lets Jo
              clear the row once the memorial app has actually shipped it.
              Backend mark_dispatched is a no-op on stock for personalised
              products, so this is a pure status flip. */}
          {order.product_is_personalised && order.status !== 'dispatched' && (
            <button
              onClick={() => markDispatched(order.id)}
              disabled={fulfilling.has(order.id)}
              className="bg-violet-700 text-white px-3 py-1 rounded text-xs hover:bg-violet-800 disabled:opacity-50"
              title="Memorial app has shipped this — clear from the queue (no stock change)"
            >
              {fulfilling.has(order.id) ? 'Marking…' : 'Mark sent'}
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
        <div className="flex items-center gap-2 mb-1.5">
          <div className="relative">
            <input
              type="search"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder="Search SKU, M#, order ID, customer, keyword…"
              className="border border-slate-300 rounded pl-8 pr-8 py-1 text-sm w-80"
            />
            <svg
              className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400"
              fill="none" viewBox="0 0 24 24" strokeWidth={1.8} stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round"
                d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
            </svg>
            {searchInput && (
              <button
                type="button"
                onClick={() => setSearchInput('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 text-xs"
                aria-label="Clear search"
              >
                ×
              </button>
            )}
          </div>
          {tab === 'all' && !search && (
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="border border-slate-300 rounded px-2 py-1 text-sm"
            >
              <option value="">Active (default)</option>
              <option value="all_incl_dispatched">All statuses (incl. dispatched)</option>
              <option value="pending">Pending only</option>
              <option value="in_progress">In progress only</option>
              <option value="made">Made only</option>
              <option value="dispatched">Dispatched only</option>
            </select>
          )}
        </div>
      </div>

      {/* Search indicator */}
      {search && (
        <div className="flex items-center justify-between bg-slate-50 border border-slate-200 rounded px-3 py-2 mb-4 text-sm">
          <span className="text-slate-700">
            Searching all orders (incl. dispatched) for
            <span className="font-semibold ml-1">&ldquo;{search}&rdquo;</span>
            <span className="text-slate-400 ml-2">· {filteredOrders.length} match{filteredOrders.length === 1 ? '' : 'es'}</span>
          </span>
          <button
            onClick={() => setSearchInput('')}
            className="text-slate-500 hover:text-slate-800 text-xs"
          >
            Clear search
          </button>
        </div>
      )}

      {/* Per-tab utility row: select-all + fulfil-all */}
      {filteredOrders.length > 0 && (
        <div className="flex items-center gap-3 mb-3">
          <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
            <input
              type="checkbox"
              checked={allVisibleSelected}
              ref={el => { if (el) el.indeterminate = someVisibleSelected }}
              onChange={toggleSelectAll}
              className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
            />
            <span>
              {allVisibleSelected
                ? `${selected.size} selected`
                : someVisibleSelected
                  ? `${selected.size} selected — select all visible`
                  : `Select all ${filteredOrders.length}`}
            </span>
          </label>
          {tab === 'ready' && !search && readyCount > 0 && selected.size === 0 && (
            <>
              <span className="text-slate-300">·</span>
              <button
                onClick={bulkFulfil}
                disabled={fulfilling.size > 0}
                className="text-sm text-emerald-700 hover:text-emerald-900 font-medium disabled:opacity-50"
              >
                {fulfilling.size > 0 ? 'Fulfilling…' : `Fulfil all ${readyCount} in view`}
              </button>
            </>
          )}
          {tab === 'all' && !search && selected.size === 0 && (() => {
            const personalisedActive = orders.filter(
              o => o.product_is_personalised && o.status !== 'dispatched' && o.status !== 'cancelled',
            ).length
            if (personalisedActive === 0) return null
            return (
              <>
                <span className="text-slate-300">·</span>
                <button
                  onClick={markAllPersonalisedSent}
                  disabled={fulfilling.size > 0}
                  className="text-sm text-violet-700 hover:text-violet-900 font-medium disabled:opacity-50"
                  title="Memorial app has shipped these — clear them from the queue"
                >
                  {fulfilling.size > 0
                    ? 'Marking…'
                    : `Mark all ${personalisedActive} personalised as sent`}
                </button>
              </>
            )
          })()}
        </div>
      )}

      {/* Content */}
      {loading ? (
        <p className="text-slate-400 text-sm">Loading…</p>
      ) : filteredOrders.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-md p-8 text-center text-slate-500">
          {search
            ? `No orders match "${search}".`
            : (
              <>
                {tab === 'ready' && 'No orders ready to ship right now.'}
                {tab === 'needs_making' && 'No orders waiting to be made.'}
                {tab === 'all' && `No ${statusFilter || ''} orders. Drop a Zenstores CSV above to import.`}
              </>
            )
          }
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

      {/* Personalised order analytics + brass calculator — share a single stats fetch */}
      <PersonalisedPanels />

      {/* Floating action bar — appears only when orders are selected */}
      {selected.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40">
          <div className="bg-slate-900 text-white rounded-lg shadow-lg border border-slate-800 flex items-center gap-4 px-4 py-3">
            <span className="text-sm">
              <span className="font-semibold">{selected.size}</span> order{selected.size === 1 ? '' : 's'} selected
            </span>
            <button
              onClick={bulkDispatchSelected}
              disabled={bulkDispatching}
              className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-4 py-1.5 rounded text-sm font-medium"
            >
              {bulkDispatching ? 'Dispatching…' : 'Dispatch selected'}
            </button>
            <button
              onClick={() => setSelected(new Set())}
              className="text-slate-300 hover:text-white text-sm"
            >
              Clear
            </button>
          </div>
        </div>
      )}
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
