'use client'

import { useState, useEffect, useCallback } from 'react'
import { api, downloadBarcodePdf } from '@/lib/api'

const MARKETPLACES = ['UK', 'US', 'CA', 'AU', 'DE', 'FR', 'IT', 'ES', 'NL']

interface ProductBarcode {
  id: number
  m_number: string
  product: number
  marketplace: string
  barcode_type: string
  barcode_value: string
  label_title: string
  condition: string
  source: string
  last_synced_at: string | null
}

function toast(msg: string) {
  const el = document.createElement('div')
  el.textContent = msg
  el.style.cssText =
    'position:fixed;bottom:24px;right:24px;background:#1e293b;color:#fff;padding:10px 18px;border-radius:8px;z-index:9999;font-size:14px;'
  document.body.appendChild(el)
  setTimeout(() => el.remove(), 3500)
}

export default function BarcodesPage() {
  const [activeTab, setActiveTab] = useState<string>('UK')
  const [barcodes, setBarcodes] = useState<ProductBarcode[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  // Selection + per-row qty (keyed by barcode.id so they're scoped to the tab)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [rowQty, setRowQty] = useState<{ [id: number]: number }>({})

  // Preview modal
  const [previewBarcode, setPreviewBarcode] = useState<ProductBarcode | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  // Sync modal
  const [syncOpen, setSyncOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<string | null>(null)

  const [pdfLoading, setPdfLoading] = useState(false)

  // Fetch barcodes scoped to the active tab + production quantities
  const fetchBarcodes = useCallback(async () => {
    setLoading(true)
    try {
      const [barcodesRes, prodRes] = await Promise.all([
        api(`/api/barcodes/?marketplace=${activeTab}`),
        api('/api/barcodes/production-quantities/'),
      ])
      const data = await barcodesRes.json()
      const list: ProductBarcode[] = data.results ?? data
      setBarcodes(list)
      setSelected(new Set())  // clear selection on tab switch

      // Default each row's qty from production sheet (keyed by M-number)
      if (prodRes.ok) {
        const prodQty = await prodRes.json() as Record<string, number>
        setRowQty(prev => {
          const next = { ...prev }
          for (const b of list) {
            if (next[b.id] === undefined) {
              next[b.id] = prodQty[b.m_number] ?? 1
            }
          }
          return next
        })
      }
    } catch {
      setError('Failed to load barcodes')
    } finally {
      setLoading(false)
    }
  }, [activeTab])

  useEffect(() => { fetchBarcodes() }, [fetchBarcodes])

  // Filter by search and sort by M-number
  const q = search.trim().toLowerCase()
  const filtered = barcodes
    .filter(b =>
      !q ||
      b.m_number.toLowerCase().includes(q) ||
      b.label_title.toLowerCase().includes(q) ||
      b.barcode_value.toLowerCase().includes(q)
    )
    .sort((a, b) => a.m_number.localeCompare(b.m_number))

  function toggleSelect(id: number) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    if (selected.size === filtered.length && filtered.length > 0) {
      setSelected(new Set())
    } else {
      setSelected(new Set(filtered.map(b => b.id)))
    }
  }

  function setQty(id: number, qty: number) {
    setRowQty(prev => ({ ...prev, [id]: Math.max(1, qty) }))
  }

  async function handlePdf() {
    if (!selected.size) return
    const items = filtered
      .filter(b => selected.has(b.id))
      .map(b => ({ barcode_id: b.id, quantity: rowQty[b.id] ?? 1 }))
    if (!items.length) return
    setPdfLoading(true)
    try {
      await downloadBarcodePdf(items)
      const totalLabels = items.reduce((sum, i) => sum + i.quantity, 0)
      toast(`PDF generated — ${items.length} SKUs, ${totalLabels} labels`)
    } catch {
      toast('PDF generation failed')
    } finally {
      setPdfLoading(false)
    }
  }

  async function openPreview(barcode: ProductBarcode) {
    setPreviewBarcode(barcode)
    setPreviewUrl(null)
    setPreviewLoading(true)
    try {
      const r = await api(`/api/barcodes/${barcode.id}/preview/`, { method: 'POST' })
      if (!r.ok) throw new Error('Preview failed')
      const blob = await r.blob()
      setPreviewUrl(URL.createObjectURL(blob))
    } catch {
      setPreviewUrl(null)
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleSync(marketplace: string) {
    setSyncOpen(true)
    setSyncing(true)
    setSyncResult(null)
    try {
      const r = await api('/api/barcodes/sync-fnskus/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ marketplace }),
      })
      const data = await r.json()
      setSyncResult(JSON.stringify(data, null, 2))
      fetchBarcodes()
    } catch {
      setSyncResult('Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  const totalLabels = filtered
    .filter(b => selected.has(b.id))
    .reduce((sum, b) => sum + (rowQty[b.id] ?? 1), 0)

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Barcodes</h1>
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search M-number, title, FNSKU…"
            className="border rounded px-3 py-1 text-sm w-64"
          />
          {/* Sync from Amazon dropdown */}
          <div className="relative group">
            <button className="border rounded px-3 py-1 text-sm hover:bg-gray-50">
              Sync from Amazon ▾
            </button>
            <div className="absolute right-0 top-full mt-1 bg-white border rounded shadow-lg z-10 hidden group-hover:block min-w-[160px]">
              <button
                onClick={() => handleSync(activeTab)}
                className="block w-full text-left px-4 py-2 text-sm hover:bg-gray-50 border-b font-medium"
              >
                Sync {activeTab} (current)
              </button>
              {MARKETPLACES.filter(m => m !== activeTab).map(m => (
                <button
                  key={m}
                  onClick={() => handleSync(m)}
                  className="block w-full text-left px-4 py-2 text-sm hover:bg-gray-50"
                >
                  Sync {m}
                </button>
              ))}
              <button
                onClick={() => handleSync('ALL')}
                className="block w-full text-left px-4 py-2 text-sm hover:bg-gray-50 border-t font-medium"
              >
                Sync ALL
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Country tabs */}
      <div className="flex border-b mb-4 gap-1 flex-wrap">
        {MARKETPLACES.map(m => (
          <button
            key={m}
            onClick={() => setActiveTab(m)}
            className={
              activeTab === m
                ? 'px-4 py-2 text-sm font-semibold bg-teal-600 text-white rounded-t'
                : 'px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-t'
            }
          >
            {m}
          </button>
        ))}
      </div>

      {/* Action bar */}
      <div className="flex items-center gap-3 mb-3 min-h-[40px]">
        {selected.size > 0 ? (
          <>
            <span className="text-sm text-gray-700">
              {selected.size} selected · {totalLabels} labels
            </span>
            <button
              onClick={handlePdf}
              disabled={pdfLoading}
              className="bg-teal-600 text-white px-4 py-1.5 rounded text-sm hover:bg-teal-700 disabled:opacity-50"
            >
              {pdfLoading ? 'Generating…' : `Print PDF (${selected.size} SKUs)`}
            </button>
            <button
              onClick={() => setSelected(new Set())}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Clear
            </button>
          </>
        ) : (
          <span className="text-sm text-gray-400">
            Tick rows to bulk-print onto Avery 27-up sheets
          </span>
        )}
      </div>

      {/* Sync result modal */}
      {syncOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-bold mb-3">SP-API Sync</h2>
            {syncing && <p className="text-gray-500">Syncing… (this may take 30–120s per marketplace)</p>}
            {syncResult && <pre className="text-xs bg-gray-50 p-3 rounded overflow-auto max-h-64">{syncResult}</pre>}
            <button
              onClick={() => setSyncOpen(false)}
              className="mt-4 bg-gray-100 px-4 py-2 rounded text-sm hover:bg-gray-200"
            >
              Close
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-gray-400 py-8">Loading {activeTab} barcodes…</p>
      ) : error ? (
        <p className="text-red-600 py-8">{error}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-100 text-left">
                <th className="p-2">M-number</th>
                <th className="p-2">Title</th>
                <th className="p-2">{activeTab} FNSKU</th>
                <th className="p-2 text-center w-36">
                  <div className="flex items-center justify-center gap-2">
                    <input
                      type="checkbox"
                      onChange={toggleSelectAll}
                      checked={selected.size === filtered.length && filtered.length > 0}
                      title="Select all"
                    />
                    <span>Qty / Print</span>
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((b, i) => (
                <tr
                  key={b.id}
                  className={i % 2 === 0 ? 'bg-[#fff9e8]' : 'bg-[#f0f7ee]'}
                >
                  <td className="p-2 font-mono font-semibold">{b.m_number}</td>
                  <td className="p-2 max-w-xs truncate" title={b.label_title}>{b.label_title}</td>
                  <td className="p-2 font-mono text-xs">
                    <button
                      className="text-teal-700 hover:underline"
                      onClick={() => openPreview(b)}
                      title="Preview label"
                    >
                      {b.barcode_value}
                    </button>
                  </td>
                  <td className="p-2 text-center">
                    <div className="flex items-center justify-center gap-2">
                      <input
                        type="number"
                        min={1}
                        value={rowQty[b.id] ?? 1}
                        onChange={e => setQty(b.id, Number(e.target.value))}
                        className="border rounded px-1 py-0.5 text-xs w-16 text-center"
                      />
                      <input
                        type="checkbox"
                        checked={selected.has(b.id)}
                        onChange={() => toggleSelect(b.id)}
                        title="Include in print batch"
                        className="w-4 h-4"
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <p className="text-gray-400 py-8 text-center">
              No {activeTab} barcodes{q ? ` matching "${search}"` : ''}. Try syncing this marketplace from Amazon.
            </p>
          )}
          {filtered.length > 0 && (
            <p className="text-xs text-gray-400 mt-3 text-right">
              {filtered.length} {activeTab} barcode{filtered.length === 1 ? '' : 's'}
              {q && ` (filtered from ${barcodes.length})`}
            </p>
          )}
        </div>
      )}

      {/* Preview modal */}
      {previewBarcode && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-sm shadow-xl">
            <h2 className="text-lg font-bold mb-2">
              {previewBarcode.barcode_value}
              <span className="ml-2 text-xs text-gray-400">{previewBarcode.marketplace}</span>
            </h2>
            <p className="text-xs text-gray-500 mb-3 truncate">{previewBarcode.label_title}</p>
            {previewLoading && <p className="text-gray-400 text-sm">Rendering preview…</p>}
            {previewUrl && (
              <img src={previewUrl} alt="Label preview" className="w-full border rounded mb-3" />
            )}
            {!previewLoading && !previewUrl && (
              <p className="text-red-500 text-sm mb-3">Preview unavailable (Labelary unreachable?)</p>
            )}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => { setPreviewBarcode(null); if (previewUrl) URL.revokeObjectURL(previewUrl) }}
                className="bg-gray-100 px-3 py-1 rounded text-sm hover:bg-gray-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
