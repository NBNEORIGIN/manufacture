'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

interface Change {
  m_number: string
  sku?: string
  field: string
  old: number
  new: number
  restock_recommended?: number
}

interface UploadResult {
  report_type: string
  preview: boolean
  changes: Change[]
  skipped: { sku: string; reason: string }[]
  total_items: number
}

interface ImportLogEntry {
  id: number
  import_type: string
  filename: string
  rows_processed: number
  rows_created: number
  rows_updated: number
  rows_skipped: number
  error_count: number
  created_at: string
}

export default function ImportsPage() {
  const [file, setFile] = useState<File | null>(null)
  const [reportType, setReportType] = useState('')
  const [result, setResult] = useState<UploadResult | null>(null)
  const [history, setHistory] = useState<ImportLogEntry[]>([])
  const [uploading, setUploading] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [message, setMessage] = useState('')

  const loadHistory = () => {
    api('/api/imports/history/').then(r => r.json()).then(setHistory).catch(() => {})
  }

  useEffect(() => { loadHistory() }, [])

  const upload = async (confirm = false) => {
    if (!file) return
    confirm ? setConfirming(true) : setUploading(true)

    const formData = new FormData()
    formData.append('file', file)
    if (reportType) formData.append('report_type', reportType)
    if (confirm) formData.append('confirm', 'true')

    try {
      const res = await api('/api/imports/upload/', { method: 'POST', body: formData })
      const data = await res.json()

      if (!res.ok) {
        setMessage(data.error || 'Upload failed')
      } else {
        setResult(data)
        if (confirm) {
          setMessage(`Applied ${data.changes.length} changes`)
          setFile(null)
          setResult(null)
          loadHistory()
        }
      }
    } catch {
      setMessage('Upload failed')
    }
    setUploading(false)
    setConfirming(false)
    setTimeout(() => setMessage(''), 5000)
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">CSV Import</h2>

      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h3 className="font-semibold mb-4">Upload Seller Central Report</h3>
        <div className="flex items-center gap-4 mb-4">
          <input
            type="file"
            accept=".csv,.tsv,.txt"
            onChange={e => { setFile(e.target.files?.[0] || null); setResult(null) }}
            className="border rounded px-3 py-2 text-sm"
          />
          <select
            value={reportType}
            onChange={e => setReportType(e.target.value)}
            className="border rounded px-3 py-2 text-sm"
          >
            <option value="">Auto-detect type</option>
            <option value="fba_inventory">FBA Inventory</option>
            <option value="sales_traffic">Sales & Traffic</option>
            <option value="restock">Restock Inventory</option>
          </select>
          <button
            onClick={() => upload(false)}
            disabled={!file || uploading}
            className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {uploading ? 'Parsing...' : 'Preview'}
          </button>
        </div>
        {message && <p className="text-sm text-red-600 mb-2">{message}</p>}

        {result && (
          <div className="border rounded p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="font-medium">
                  {result.report_type} — {result.total_items} items parsed
                </p>
                <p className="text-sm text-gray-500">
                  {result.changes.length} changes, {result.skipped.length} skipped
                </p>
              </div>
              {result.preview && result.changes.length > 0 && (
                <button
                  onClick={() => upload(true)}
                  disabled={confirming}
                  className="bg-green-600 text-white px-4 py-2 rounded text-sm hover:bg-green-700 disabled:opacity-50"
                >
                  {confirming ? 'Applying...' : `Confirm ${result.changes.length} Changes`}
                </button>
              )}
            </div>

            {result.changes.length > 0 && (
              <table className="w-full text-sm mb-4">
                <thead>
                  <tr className="border-b bg-gray-50">
                    <th className="text-left px-3 py-2">M-Number</th>
                    <th className="text-left px-3 py-2">SKU</th>
                    <th className="text-left px-3 py-2">Field</th>
                    <th className="text-right px-3 py-2">Old</th>
                    <th className="text-right px-3 py-2">New</th>
                  </tr>
                </thead>
                <tbody>
                  {result.changes.slice(0, 50).map((c, i) => (
                    <tr key={i} className="border-b">
                      <td className="px-3 py-1.5 font-mono">{c.m_number}</td>
                      <td className="px-3 py-1.5 text-gray-500">{c.sku || '-'}</td>
                      <td className="px-3 py-1.5">{c.field}</td>
                      <td className="px-3 py-1.5 text-right">{c.old}</td>
                      <td className="px-3 py-1.5 text-right font-semibold">{c.new}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {result.skipped.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer text-gray-500">
                  {result.skipped.length} skipped items
                </summary>
                <div className="mt-2 max-h-40 overflow-y-auto">
                  {result.skipped.slice(0, 20).map((s, i) => (
                    <p key={i} className="text-gray-400">{s.sku}: {s.reason}</p>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="font-semibold mb-4">Import History</h3>
        {history.length === 0 ? (
          <p className="text-gray-400 text-sm">No imports yet (seed imports from management commands are logged here)</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-gray-50">
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">File</th>
                <th className="text-right px-3 py-2">Processed</th>
                <th className="text-right px-3 py-2">Created</th>
                <th className="text-right px-3 py-2">Updated</th>
                <th className="text-right px-3 py-2">Skipped</th>
                <th className="text-left px-3 py-2">Date</th>
              </tr>
            </thead>
            <tbody>
              {history.map(log => (
                <tr key={log.id} className="border-b">
                  <td className="px-3 py-1.5">{log.import_type}</td>
                  <td className="px-3 py-1.5 text-gray-500 max-w-xs truncate">{log.filename.split(/[/\\]/).pop()}</td>
                  <td className="px-3 py-1.5 text-right">{log.rows_processed}</td>
                  <td className="px-3 py-1.5 text-right">{log.rows_created}</td>
                  <td className="px-3 py-1.5 text-right">{log.rows_updated}</td>
                  <td className="px-3 py-1.5 text-right">{log.rows_skipped}</td>
                  <td className="px-3 py-1.5 text-gray-400">{new Date(log.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
