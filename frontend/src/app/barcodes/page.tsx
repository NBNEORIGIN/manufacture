'use client'

import { useState, useEffect, useCallback } from 'react'
import { api } from '@/lib/api'

const MARKETPLACES = ['UK', 'US', 'CA', 'AU', 'DE']

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

interface BarcodeMap {
  [mNumber: string]: {
    product_id: number
    label_title: string
    barcodes: { [marketplace: string]: ProductBarcode }
  }
}

function toast(msg: string) {
  // Simple toast using alert — matches existing app's lightweight approach
  const el = document.createElement('div')
  el.textContent = msg
  el.style.cssText =
    'position:fixed;bottom:24px;right:24px;background:#1e293b;color:#fff;padding:10px 18px;border-radius:8px;z-index:9999;font-size:14px;'
  document.body.appendChild(el)
  setTimeout(() => el.remove(), 3500)
}

export default function BarcodesPage() {
  const [barcodes, setBarcodes] = useState<ProductBarcode[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Bulk print state
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkQty, setBulkQty] = useState(1)
  const [bulkMarketplace, setBulkMarketplace] = useState('UK')

  // Preview modal
  const [previewBarcode, setPreviewBarcode] = useState<ProductBarcode | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  // Add/edit modal
  const [editBarcode, setEditBarcode] = useState<Partial<ProductBarcode> | null>(null)
  const [editProductId, setEditProductId] = useState<number | null>(null)
  const [editMarketplace, setEditMarketplace] = useState('UK')
  const [saving, setSaving] = useState(false)

  // Sync modal
  const [syncOpen, setSyncOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<string | null>(null)

  // Per-row qty
  const [rowQty, setRowQty] = useState<{ [id: number]: number }>({})

  const fetchBarcodes = useCallback(async () => {
    try {
      const r = await api('/api/barcodes/?page_size=500')
      const data = await r.json()
      setBarcodes(data.results ?? data)
    } catch {
      setError('Failed to load barcodes')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchBarcodes() }, [fetchBarcodes])

  // Build a product → marketplace → barcode map
  const grouped: BarcodeMap = {}
  for (const b of barcodes) {
    if (!grouped[b.m_number]) {
      grouped[b.m_number] = { product_id: b.product, label_title: b.label_title, barcodes: {} }
    }
    grouped[b.m_number].barcodes[b.marketplace] = b
  }
  const rows = Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b))

  function toggleSelect(productId: number) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(productId)) next.delete(productId)
      else next.add(productId)
      return next
    })
  }

  async function handleSinglePrint(barcode: ProductBarcode, qty: number) {
    const r = await api(`/api/barcodes/${barcode.id}/print/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quantity: qty }),
    })
    if (!r.ok) { toast('Print failed'); return }
    toast(`Queued 1 job — see Print Queue`)
  }

  async function handleBulkPrint() {
    if (!selected.size) return
    const items: { barcode_id: number; quantity: number }[] = []
    for (const productId of Array.from(selected)) {
      const mNumber = Object.entries(grouped).find(([, v]) => v.product_id === productId)?.[0]
      if (!mNumber) continue
      const barcode = grouped[mNumber].barcodes[bulkMarketplace]
      if (barcode) items.push({ barcode_id: barcode.id, quantity: bulkQty })
    }
    if (!items.length) { toast('No barcodes for selected marketplace'); return }
    const r = await api('/api/barcodes/bulk-print/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    })
    if (!r.ok) { toast('Bulk print failed'); return }
    toast(`Queued ${items.length} jobs — see Print Queue`)
    setSelected(new Set())
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

  async function handleSaveBarcode() {
    if (!editBarcode) return
    setSaving(true)
    try {
      const isNew = !editBarcode.id
      const url = isNew ? '/api/barcodes/' : `/api/barcodes/${editBarcode.id}/`
      const r = await api(url, {
        method: isNew ? 'POST' : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editBarcode),
      })
      if (!r.ok) { toast('Save failed'); return }
      toast(isNew ? 'Barcode added' : 'Barcode updated')
      setEditBarcode(null)
      fetchBarcodes()
    } finally {
      setSaving(false)
    }
  }

  async function handleSync(marketplace: string) {
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

  if (loading) return <p className="text-gray-400 py-8">Loading barcodes…</p>
  if (error) return <p className="text-red-600 py-8">{error}</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Barcodes</h1>
        <div className="flex gap-2">
          {selected.size > 0 && (
            <>
              <select
                value={bulkMarketplace}
                onChange={e => setBulkMarketplace(e.target.value)}
                className="border rounded px-2 py-1 text-sm"
              >
                {MARKETPLACES.map(m => <option key={m}>{m}</option>)}
              </select>
              <input
                type="number"
                min={1}
                value={bulkQty}
                onChange={e => setBulkQty(Number(e.target.value))}
                className="border rounded px-2 py-1 text-sm w-16"
                placeholder="Qty"
              />
              <button
                onClick={handleBulkPrint}
                className="bg-teal-600 text-white px-3 py-1 rounded text-sm hover:bg-teal-700"
              >
                Print selected ({selected.size})
              </button>
            </>
          )}
          {/* Sync from Amazon dropdown */}
          <div className="relative group">
            <button className="border rounded px-3 py-1 text-sm hover:bg-gray-50">
              Sync from Amazon ▾
            </button>
            <div className="absolute right-0 top-full mt-1 bg-white border rounded shadow-lg z-10 hidden group-hover:block min-w-[140px]">
              {[...MARKETPLACES, 'ALL'].map(m => (
                <button
                  key={m}
                  onClick={() => { setSyncOpen(true); handleSync(m) }}
                  className="block w-full text-left px-4 py-2 text-sm hover:bg-gray-50"
                >
                  Sync {m}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Sync result modal */}
      {syncOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-bold mb-3">SP-API Sync</h2>
            {syncing && <p className="text-gray-500">Syncing…</p>}
            {syncResult && <pre className="text-xs bg-gray-50 p-3 rounded overflow-auto max-h-48">{syncResult}</pre>}
            <button
              onClick={() => setSyncOpen(false)}
              className="mt-4 bg-gray-100 px-4 py-2 rounded text-sm hover:bg-gray-200"
            >
              Close
            </button>
          </div>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="p-2 w-8">
                <input
                  type="checkbox"
                  onChange={e => {
                    if (e.target.checked) setSelected(new Set(rows.map(([, v]) => v.product_id)))
                    else setSelected(new Set())
                  }}
                  checked={selected.size === rows.length && rows.length > 0}
                />
              </th>
              <th className="p-2">M-number</th>
              <th className="p-2">Title</th>
              {MARKETPLACES.map(m => (
                <th key={m} className="p-2 text-center">{m} FNSKU</th>
              ))}
              <th className="p-2 text-center">Qty</th>
              <th className="p-2 text-center">Print</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([mNumber, { product_id, label_title, barcodes: bc }], i) => (
              <tr
                key={mNumber}
                className={i % 2 === 0 ? 'bg-[#fff9e8]' : 'bg-[#f0f7ee]'}
              >
                <td className="p-2">
                  <input
                    type="checkbox"
                    checked={selected.has(product_id)}
                    onChange={() => toggleSelect(product_id)}
                  />
                </td>
                <td className="p-2 font-mono font-semibold">{mNumber}</td>
                <td className="p-2 max-w-xs truncate" title={label_title}>{label_title}</td>
                {MARKETPLACES.map(m => {
                  const b = bc[m]
                  return (
                    <td key={m} className="p-2 text-center font-mono text-xs">
                      {b ? (
                        <button
                          className="text-teal-700 hover:underline"
                          onClick={() => openPreview(b)}
                          title="Preview label"
                        >
                          {b.barcode_value}
                        </button>
                      ) : (
                        <button
                          className="text-gray-300 hover:text-teal-600"
                          onClick={() => setEditBarcode({ product: product_id, marketplace: m, barcode_type: 'FNSKU', label_title, condition: 'New' })}
                          title="Add barcode"
                        >
                          — +
                        </button>
                      )}
                    </td>
                  )
                })}
                <td className="p-2 text-center">
                  <input
                    type="number"
                    min={1}
                    value={rowQty[product_id] ?? 1}
                    onChange={e => setRowQty(prev => ({ ...prev, [product_id]: Number(e.target.value) }))}
                    className="border rounded px-1 py-0.5 text-xs w-14 text-center"
                  />
                </td>
                <td className="p-2 text-center">
                  <div className="flex gap-1 justify-center flex-wrap">
                    {MARKETPLACES.filter(m => bc[m]).map(m => (
                      <button
                        key={m}
                        onClick={() => handleSinglePrint(bc[m], rowQty[product_id] ?? 1)}
                        className="bg-teal-50 border border-teal-300 text-teal-800 px-2 py-0.5 rounded text-xs hover:bg-teal-100"
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="text-gray-400 py-8 text-center">
            No barcodes yet. Run <code>python manage.py seed_barcodes</code> or sync from Amazon.
          </p>
        )}
      </div>

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
                onClick={() => handleSinglePrint(previewBarcode, 1)}
                className="bg-teal-600 text-white px-3 py-1 rounded text-sm hover:bg-teal-700"
              >
                Print 1 test
              </button>
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

      {/* Add/edit barcode modal */}
      {editBarcode !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-bold mb-4">{editBarcode.id ? 'Edit Barcode' : 'Add Barcode'}</h2>
            <div className="grid gap-3">
              <label className="text-sm font-medium">
                Marketplace
                <select
                  value={editBarcode.marketplace ?? 'UK'}
                  onChange={e => setEditBarcode(prev => prev ? { ...prev, marketplace: e.target.value } : prev)}
                  className="border rounded px-2 py-1 w-full mt-1"
                >
                  {MARKETPLACES.map(m => <option key={m}>{m}</option>)}
                </select>
              </label>
              <label className="text-sm font-medium">
                Type
                <select
                  value={editBarcode.barcode_type ?? 'FNSKU'}
                  onChange={e => setEditBarcode(prev => prev ? { ...prev, barcode_type: e.target.value } : prev)}
                  className="border rounded px-2 py-1 w-full mt-1"
                >
                  <option>FNSKU</option>
                  <option>UPC</option>
                  <option>EAN</option>
                </select>
              </label>
              <label className="text-sm font-medium">
                Barcode value
                <input
                  type="text"
                  value={editBarcode.barcode_value ?? ''}
                  onChange={e => setEditBarcode(prev => prev ? { ...prev, barcode_value: e.target.value } : prev)}
                  className="border rounded px-2 py-1 w-full mt-1 font-mono"
                  placeholder="X001XXXXXX"
                />
              </label>
              <label className="text-sm font-medium">
                Label title
                <input
                  type="text"
                  value={editBarcode.label_title ?? ''}
                  onChange={e => setEditBarcode(prev => prev ? { ...prev, label_title: e.target.value } : prev)}
                  className="border rounded px-2 py-1 w-full mt-1"
                  maxLength={80}
                />
              </label>
              <label className="text-sm font-medium">
                Condition
                <input
                  type="text"
                  value={editBarcode.condition ?? 'New'}
                  onChange={e => setEditBarcode(prev => prev ? { ...prev, condition: e.target.value } : prev)}
                  className="border rounded px-2 py-1 w-full mt-1"
                />
              </label>
            </div>
            <div className="flex gap-2 justify-end mt-4">
              <button
                onClick={handleSaveBarcode}
                disabled={saving}
                className="bg-teal-600 text-white px-4 py-1.5 rounded text-sm hover:bg-teal-700 disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                onClick={() => setEditBarcode(null)}
                className="bg-gray-100 px-4 py-1.5 rounded text-sm hover:bg-gray-200"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
