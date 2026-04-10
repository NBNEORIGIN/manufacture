const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000'

function getCsrfToken(): string {
  if (typeof document === 'undefined') return ''
  const value = `; ${document.cookie}`
  const parts = value.split('; csrftoken=')
  if (parts.length === 2) return parts.pop()!.split(';').shift() || ''
  return ''
}

export function api(path: string, init?: RequestInit) {
  const method = ((init?.method) || 'GET').toUpperCase()
  const mutating = ['POST', 'PATCH', 'PUT', 'DELETE'].includes(method)

  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> || {}),
  }
  if (mutating) {
    const token = getCsrfToken()
    if (token) headers['X-CSRFToken'] = token
  }

  const opts: RequestInit = {
    ...init,
    credentials: 'include' as RequestCredentials,
    headers,
  }
  return fetch(`${API_BASE}${path}`, opts)
}

// --- Barcode API helpers ---

export interface PrintJob {
  id: number
  barcode: number
  m_number: string
  marketplace: string
  barcode_value: string
  quantity: number
  command_language: string
  status: string
  agent_id: string
  claimed_at: string | null
  printed_at: string | null
  error_message: string
  retry_count: number
  created_at: string
}

export async function listBarcodes(params: { product?: number; marketplace?: string }) {
  const qs = new URLSearchParams()
  if (params.product) qs.set('product', String(params.product))
  if (params.marketplace) qs.set('marketplace', params.marketplace)
  return api(`/api/barcodes/?${qs}`)
}

export async function getBarcodePreview(id: number): Promise<Blob> {
  const r = await api(`/api/barcodes/${id}/preview/`, { method: 'POST' })
  if (!r.ok) throw new Error('Preview failed')
  return r.blob()
}

export async function printBarcode(id: number, quantity: number): Promise<PrintJob> {
  const r = await api(`/api/barcodes/${id}/print/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ quantity }),
  })
  if (!r.ok) throw new Error('Print failed')
  return r.json()
}

export async function bulkPrint(items: Array<{ barcode_id: number; quantity: number }>): Promise<PrintJob[]> {
  const r = await api('/api/barcodes/bulk-print/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  })
  if (!r.ok) throw new Error('Bulk print failed')
  return r.json()
}

export async function listPrintJobs(status?: string): Promise<PrintJob[]> {
  const url = status ? `/api/print-jobs/?status=${status}` : '/api/print-jobs/'
  const r = await api(url)
  if (!r.ok) throw new Error('Failed to fetch print jobs')
  const data = await r.json()
  return data.results ?? data
}

export async function getPendingCount(): Promise<{ count: number }> {
  const r = await api('/api/print-jobs/pending-count/')
  if (!r.ok) throw new Error('Failed to fetch pending count')
  return r.json()
}

export async function cancelPrintJob(id: number): Promise<void> {
  const r = await api(`/api/print-jobs/${id}/cancel/`, { method: 'POST' })
  if (!r.ok) throw new Error('Cancel failed')
}

export async function retryPrintJob(id: number): Promise<PrintJob> {
  const r = await api(`/api/print-jobs/${id}/retry/`, { method: 'POST' })
  if (!r.ok) throw new Error('Retry failed')
  return r.json()
}

export async function downloadBarcodePdf(items: Array<{ barcode_id: number; quantity: number }>): Promise<void> {
  const r = await api('/api/barcodes/pdf/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  })
  if (!r.ok) throw new Error('PDF generation failed')
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'barcode-labels.pdf'
  a.click()
  URL.revokeObjectURL(url)
}
