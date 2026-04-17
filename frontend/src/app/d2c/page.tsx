'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '@/lib/api'

interface ZenstoresOrder {
  order_id: string
  sku: string
  m_number: string
  description: string
  quantity: number
  flags: string
  channel: string
}

interface Exclusion {
  m_number: string
  reason: string
  added_by: string
  created_at: string
}

export default function D2CPage() {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [orders, setOrders] = useState<ZenstoresOrder[]>([])
  const [skipped, setSkipped] = useState<{ sku: string; reason: string }[]>([])
  const [uploadError, setUploadError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')
  const [exclusions, setExclusions] = useState<Exclusion[]>([])
  const [dragging, setDragging] = useState(false)
  const dragCounter = useRef(0)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api('/api/restock/exclusions/')
      .then(r => r.json())
      .then(d => setExclusions(d.exclusions || []))
      .catch(() => {})
  }, [])

  const handleFile = useCallback((f: File | null) => {
    setFile(f)
    setOrders([])
    setSkipped([])
    setUploadError('')
    setSuccessMsg('')
  }, [])

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
        handleFile(f)
      } else {
        setUploadError('Only CSV, TSV, or TXT files are supported')
      }
    }
  }, [handleFile])

  const handleUpload = async (confirm = false) => {
    if (!file) return
    confirm ? setConfirming(true) : setUploading(true)
    setUploadError('')
    if (!confirm) {
      setOrders([])
      setSkipped([])
      setSuccessMsg('')
    }

    const formData = new FormData()
    formData.append('file', file)
    formData.append('report_type', 'zenstores')
    if (confirm) formData.append('confirm', 'true')

    try {
      const res = await api('/api/imports/upload/', { method: 'POST', body: formData })
      const data = await res.json()
      if (!res.ok) {
        setUploadError(data.error || 'Upload failed — check the file format')
        return
      }

      if (confirm) {
        setSuccessMsg(`Imported ${data.changes.length} orders to the dispatch queue`)
        setOrders([])
        setSkipped([])
        setFile(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
      } else {
        const items: ZenstoresOrder[] = data.changes || []
        setOrders(items)
        setSkipped(data.skipped || [])
        if (items.length === 0 && (data.skipped || []).length === 0) {
          setUploadError('No orders parsed — check the CSV format')
        }
      }
    } catch {
      setUploadError('Upload failed — check the file format')
    } finally {
      setUploading(false)
      setConfirming(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-2xl font-bold">Direct-to-Consumer (D2C)</h2>
        <a
          href="/dispatch"
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-700"
        >
          Open Dispatch Queue &rarr;
        </a>
      </div>
      <p className="text-gray-500 text-sm mb-8">
        Personalised and made-to-order workflow. These products are excluded from FBA restock planning.
      </p>

      {/* Zenstores upload */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-6 mb-6">
        <h3 className="text-base font-semibold mb-1">Zenstores Order Import</h3>
        <p className="text-xs text-gray-500 mb-4">
          Upload a Zenstores Order Export CSV to import D2C orders. Already-imported orders are shown in the skipped count.
        </p>

        {/* Drag-and-drop zone */}
        <div
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-8 mb-4 text-center cursor-pointer transition-colors ${
            dragging
              ? 'border-blue-500 bg-blue-50'
              : file
                ? 'border-green-300 bg-green-50'
                : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.tsv,.txt"
            onChange={e => handleFile(e.target.files?.[0] || null)}
            className="hidden"
          />
          {file ? (
            <div>
              <p className="text-sm font-medium text-green-700">{file.name}</p>
              <p className="text-xs text-gray-400 mt-1">
                {(file.size / 1024).toFixed(1)} KB — click or drop to replace
              </p>
            </div>
          ) : (
            <div>
              <svg className="mx-auto h-10 w-10 text-gray-300 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <p className="text-sm text-gray-500">
                <span className="font-medium text-blue-600">Click to browse</span> or drag and drop your Zenstores CSV
              </p>
              <p className="text-xs text-gray-400 mt-1">CSV, TSV, or TXT files</p>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3 mb-4">
          <button
            onClick={() => handleUpload(false)}
            disabled={!file || uploading}
            className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {uploading ? 'Parsing...' : 'Preview'}
          </button>
          {file && (
            <button
              onClick={() => { handleFile(null); if (fileInputRef.current) fileInputRef.current.value = '' }}
              className="text-gray-400 hover:text-gray-600 text-sm"
            >
              Clear
            </button>
          )}
        </div>

        {uploadError && <p className="text-red-600 text-sm mb-3">{uploadError}</p>}
        {successMsg && (
          <div className="bg-green-50 border border-green-200 rounded p-3 mb-3 flex items-center justify-between">
            <p className="text-green-700 text-sm">{successMsg}</p>
            <a href="/dispatch" className="text-green-700 text-sm font-medium hover:underline">
              View Dispatch Queue &rarr;
            </a>
          </div>
        )}

        {(orders.length > 0 || skipped.length > 0) && (
          <div className="border rounded p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm text-gray-600">
                <span className="font-semibold">{orders.length}</span> new orders
                {skipped.length > 0 && (
                  <span className="text-gray-400 ml-2">· {skipped.length} already imported (skipped)</span>
                )}
              </p>
              {orders.length > 0 && (
                <button
                  onClick={() => handleUpload(true)}
                  disabled={confirming}
                  className="bg-green-600 text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                >
                  {confirming ? 'Importing...' : `Import ${orders.length} Orders`}
                </button>
              )}
            </div>

            {orders.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b text-left">
                      <th className="px-3 py-2 font-semibold">Order ID</th>
                      <th className="px-3 py-2 font-semibold">SKU</th>
                      <th className="px-3 py-2 font-semibold">M-Number</th>
                      <th className="px-3 py-2 font-semibold">Description</th>
                      <th className="px-3 py-2 font-semibold text-right">Qty</th>
                      <th className="px-3 py-2 font-semibold">Channel</th>
                      <th className="px-3 py-2 font-semibold">Flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((o, i) => (
                      <tr key={i} className="border-b last:border-0 hover:bg-gray-50">
                        <td className="px-3 py-2 font-mono text-xs">{o.order_id}</td>
                        <td className="px-3 py-2 font-mono text-xs">{o.sku}</td>
                        <td className="px-3 py-2 font-mono text-xs text-gray-500">{o.m_number || '—'}</td>
                        <td className="px-3 py-2 text-gray-700 max-w-xs truncate" title={o.description}>
                          {o.description}
                        </td>
                        <td className="px-3 py-2 text-right">{o.quantity}</td>
                        <td className="px-3 py-2 text-gray-500 text-xs">{o.channel}</td>
                        <td className="px-3 py-2 text-xs text-gray-500">{o.flags}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {skipped.length > 0 && (
              <details className="text-sm mt-3">
                <summary className="cursor-pointer text-gray-500">
                  {skipped.length} skipped items
                </summary>
                <div className="mt-2 max-h-40 overflow-y-auto">
                  {skipped.slice(0, 20).map((s, i) => (
                    <p key={i} className="text-gray-400">{s.sku}: {s.reason}</p>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </div>

      {/* Personalised items exclusion list */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-6">
        <h3 className="text-base font-semibold mb-1">Personalised Products (D2C Only)</h3>
        <p className="text-xs text-gray-500 mb-4">
          M-numbers listed here are excluded from FBA restock plans. Toggle the &ldquo;P&rdquo; checkbox on the
          FBA Restock Planner to add or remove items.
        </p>
        {exclusions.length === 0 ? (
          <p className="text-gray-400 text-sm">No personalised products configured.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-gray-500 text-xs">
                <th className="text-left py-1.5 font-medium">M-Number</th>
                <th className="text-left py-1.5 font-medium">Reason</th>
                <th className="text-left py-1.5 font-medium">Added by</th>
              </tr>
            </thead>
            <tbody>
              {exclusions.map(ex => (
                <tr key={ex.m_number} className="border-b last:border-0">
                  <td className="py-1.5 font-mono text-xs">{ex.m_number}</td>
                  <td className="py-1.5 text-gray-600">{ex.reason || '—'}</td>
                  <td className="py-1.5 text-gray-400 text-xs">{ex.added_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
