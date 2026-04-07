'use client'

import { useState, useEffect } from 'react'
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
  const [orders, setOrders] = useState<ZenstoresOrder[]>([])
  const [skipped, setSkipped] = useState<{ sku: string; reason: string }[]>([])
  const [uploadError, setUploadError] = useState('')
  const [exclusions, setExclusions] = useState<Exclusion[]>([])

  useEffect(() => {
    api('/api/restock/exclusions/')
      .then(r => r.json())
      .then(d => setExclusions(d.exclusions || []))
      .catch(() => {})
  }, [])

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setUploadError('')
    setOrders([])
    setSkipped([])
    const formData = new FormData()
    formData.append('file', file)
    formData.append('report_type', 'zenstores')
    try {
      const res = await api('/api/imports/upload/', { method: 'POST', body: formData })
      const data = await res.json()
      if (!res.ok) {
        setUploadError(data.error || 'Upload failed — check the file format')
        return
      }
      // apply_zenstores preview returns changes[], not items[]
      const items: ZenstoresOrder[] = data.changes || []
      setOrders(items)
      setSkipped(data.skipped || [])
      if (items.length === 0 && (data.skipped || []).length === 0) {
        setUploadError('No orders parsed — check the CSV format')
      }
    } catch {
      setUploadError('Upload failed — check the file format')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Direct-to-Consumer (D2C)</h2>
      <p className="text-gray-500 text-sm mb-8">
        Personalised and made-to-order workflow. These products are excluded from FBA restock planning.
      </p>

      {/* Zenstores upload */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-100 p-6 mb-6">
        <h3 className="text-base font-semibold mb-1">Zenstores Order Import</h3>
        <p className="text-xs text-gray-500 mb-4">
          Upload a Zenstores Order Export CSV to view D2C orders. Already-imported orders are shown in the skipped count.
        </p>
        <div className="flex items-center gap-3 mb-4">
          <input
            type="file"
            accept=".csv,.tsv,.txt"
            onChange={e => setFile(e.target.files?.[0] || null)}
            className="text-sm text-gray-700 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-sm file:font-medium file:bg-gray-100 file:text-gray-700 hover:file:bg-gray-200"
          />
          <button
            onClick={handleUpload}
            disabled={!file || uploading}
            className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {uploading ? 'Parsing…' : 'Upload & Parse'}
          </button>
        </div>

        {uploadError && <p className="text-red-600 text-sm mb-3">{uploadError}</p>}

        {(orders.length > 0 || skipped.length > 0) && (
          <p className="text-sm text-gray-600 mb-3">
            <span className="font-semibold">{orders.length}</span> new orders parsed
            {skipped.length > 0 && (
              <span className="text-gray-400 ml-2">· {skipped.length} already imported (skipped)</span>
            )}
          </p>
        )}

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
                    <td
                      className="px-3 py-2 text-gray-700 max-w-xs truncate"
                      title={o.description}
                    >
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
