'use client'

import { useEffect, useState, useCallback } from 'react'
import { api } from '@/lib/api'
import HelpButton from '@/components/HelpButton'

interface ShipmentListItem {
  id: number
  country: string
  status: string
  shipment_date: string | null
  total_units: number
  box_count: number
  notes: string
  item_count: number
  created_at: string
}

interface ShipmentItem {
  id: number
  m_number: string
  description: string
  sku: string
  quantity: number
  quantity_shipped: number
  box_number: number | null
}

interface ShipmentDetail {
  id: number
  country: string
  status: string
  shipment_date: string | null
  total_units: number
  box_count: number
  notes: string
  items: ShipmentItem[]
}

interface Stats {
  shipped: { total_shipments: number; total_units: number }
  in_progress: { total_shipments: number; total_units: number }
  by_country: { country: string; shipments: number; units: number }[]
}

const STATUS_COLOURS: Record<string, string> = {
  planning: 'bg-yellow-100 text-yellow-800',
  packing: 'bg-blue-100 text-blue-800',
  labelled: 'bg-purple-100 text-purple-800',
  shipped: 'bg-green-100 text-green-800',
}

const COUNTRY_DISPLAY: Record<string, string> = {
  UK: 'GB', GB: 'GB', US: 'US', CA: 'CA', AU: 'AU', FR: 'FR', DE: 'DE', IT: 'IT',
}

const COUNTRY_COLOURS: Record<string, string> = {
  GB: 'bg-blue-700 text-white',
  US: 'bg-red-700 text-white',
  CA: 'bg-red-600 text-white',
  AU: 'bg-yellow-600 text-white',
  FR: 'bg-blue-600 text-white',
  DE: 'bg-gray-800 text-white',
  IT: 'bg-green-700 text-white',
}

function CountryBadge({ country }: { country: string }) {
  const code = COUNTRY_DISPLAY[country.toUpperCase()] || country
  const colours = COUNTRY_COLOURS[code] || 'bg-gray-500 text-white'
  return (
    <span className={`inline-flex items-center justify-center px-1.5 py-0.5 rounded text-xs font-bold tracking-wide ${colours}`}>
      {code}
    </span>
  )
}

type SortOption = 'recent' | 'oldest' | 'country' | 'units'

// ── Confirm dialog ─────────────────────────────────────────────────────────

function ConfirmDialog({
  open, title, message, onConfirm, onCancel, confirmLabel, danger,
}: {
  open: boolean; title: string; message: string
  onConfirm: () => void; onCancel: () => void
  confirmLabel?: string; danger?: boolean
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onCancel}>
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm mx-4" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold mb-2">{title}</h3>
        <p className="text-sm text-gray-700 mb-4">{message}</p>
        <div className="flex gap-2 justify-end">
          <button onClick={onCancel} className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded text-sm">Cancel</button>
          <button
            onClick={onConfirm}
            className={`px-3 py-1.5 rounded text-sm text-white ${danger ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'}`}
          >
            {confirmLabel || 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Add items form ─────────────────────────────────────────────────────────

function AddItemsForm({
  shipmentId, onDone,
}: { shipmentId: number; onDone: () => void }) {
  const [product, setProduct] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [boxNumber, setBoxNumber] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const r = await api(`/api/shipments/${shipmentId}/add-items/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: [{
            product: Number(product),
            quantity: Number(quantity),
            box_number: boxNumber ? Number(boxNumber) : null,
          }],
        }),
      })
      if (r.ok) {
        setProduct('')
        setQuantity('1')
        setBoxNumber('')
        onDone()
      } else {
        const data = await r.json().catch(() => ({}))
        setError(data.detail || data.error || `Error ${r.status}`)
      }
    } catch {
      setError('Network error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-3 p-3 bg-gray-50 rounded border">
      <p className="text-xs text-gray-600 mb-2">
        Add a product to this shipment. Enter the product ID (numeric, visible on
        the Products tab), the quantity to ship, and optionally a box number for
        packing. You can add multiple products one at a time.
      </p>
      <form onSubmit={submit} className="flex flex-wrap gap-2 items-end">
        <label className="text-xs">
          Product ID
          <input type="number" value={product} onChange={e => setProduct(e.target.value)} required className="block border rounded px-2 py-1 w-24" />
        </label>
        <label className="text-xs">
          Qty
          <input type="number" min="1" value={quantity} onChange={e => setQuantity(e.target.value)} required className="block border rounded px-2 py-1 w-16" />
        </label>
        <label className="text-xs">
          Box #
          <input type="number" value={boxNumber} onChange={e => setBoxNumber(e.target.value)} className="block border rounded px-2 py-1 w-16" placeholder="opt." />
        </label>
        <button type="submit" disabled={busy} className="px-3 py-1 bg-blue-600 text-white rounded text-xs disabled:opacity-50">
          {busy ? 'Adding…' : 'Add'}
        </button>
      </form>
      {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function ShipmentsPage() {
  const [shipments, setShipments] = useState<ShipmentListItem[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [selected, setSelected] = useState<ShipmentDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [countryFilter, setCountryFilter] = useState('')
  const [sortBy, setSortBy] = useState<SortOption>('recent')
  const [showForm, setShowForm] = useState(false)
  const [newCountry, setNewCountry] = useState('UK')
  const [message, setMessage] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null)
  const [showAddItems, setShowAddItems] = useState(false)

  const loadShipments = useCallback(() => {
    const params = new URLSearchParams()
    if (filter) params.set('status', filter)
    if (countryFilter) params.set('country', countryFilter)
    params.set('page_size', '100')

    setLoadError('')
    Promise.all([
      api(`/api/shipments/?${params}`).then(r => {
        if (!r.ok) throw new Error(`Shipments API returned ${r.status}`)
        return r.json()
      }),
      api('/api/shipments/stats/').then(r => {
        if (!r.ok) throw new Error(`Stats API returned ${r.status}`)
        return r.json()
      }),
    ]).then(([data, statsData]) => {
      setShipments(data.results || [])
      setStats(statsData)
      setLoading(false)
    }).catch(err => {
      setLoadError(err.message || 'Failed to load shipments')
      setLoading(false)
    })
  }, [filter, countryFilter])

  useEffect(() => { loadShipments() }, [loadShipments])

  const viewDetail = async (id: number) => {
    const res = await api(`/api/shipments/${id}/`)
    const data = await res.json()
    setSelected(data)
    setShowAddItems(false)
  }

  const createShipment = async () => {
    setCreating(true)
    setCreateError('')
    try {
      const res = await api('/api/shipments/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ country: newCountry }),
      })
      if (res.ok) {
        setShowForm(false)
        setMessage('Shipment created')
        setNewCountry('UK')
        loadShipments()
        setTimeout(() => setMessage(''), 3000)
      } else {
        const data = await res.json().catch(() => ({}))
        setCreateError(data.detail || data.error || `Error ${res.status}`)
      }
    } catch (e) {
      setCreateError('Network error — check your connection')
    } finally {
      setCreating(false)
    }
  }

  const markShipped = async (id: number) => {
    await api(`/api/shipments/${id}/mark-shipped/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    loadShipments()
    if (selected?.id === id) viewDetail(id)
    setMessage('Shipment marked as shipped')
    setTimeout(() => setMessage(''), 3000)
  }

  const deleteShipment = async (id: number) => {
    setDeleteConfirm(null)
    try {
      const res = await api(`/api/shipments/${id}/`, { method: 'DELETE' })
      if (res.ok || res.status === 204) {
        if (selected?.id === id) setSelected(null)
        loadShipments()
        setMessage('Shipment deleted')
        setTimeout(() => setMessage(''), 3000)
      } else {
        setMessage(`Delete failed: ${res.status}`)
        setTimeout(() => setMessage(''), 5000)
      }
    } catch {
      setMessage('Delete failed — network error')
      setTimeout(() => setMessage(''), 5000)
    }
  }

  const sortedShipments = [...shipments].sort((a, b) => {
    if (sortBy === 'recent') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    if (sortBy === 'oldest') return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    if (sortBy === 'country') return a.country.localeCompare(b.country)
    if (sortBy === 'units') return b.total_units - a.total_units
    return 0
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-bold">FBA Shipments</h2>
          <HelpButton tabKey="shipments" />
          <button
            onClick={() => { setShowForm(!showForm); setCreateError('') }}
            className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700"
          >
            New Shipment
          </button>
          {message && <span className="text-green-600 text-sm font-medium">{message}</span>}
        </div>
        <div className="flex items-center gap-2">
          <select value={filter} onChange={e => setFilter(e.target.value)} className="border rounded px-3 py-2 text-sm">
            <option value="">All statuses</option>
            <option value="planning">Planning</option>
            <option value="packing">Packing</option>
            <option value="labelled">Labelled</option>
            <option value="shipped">Shipped</option>
          </select>
          <select value={countryFilter} onChange={e => setCountryFilter(e.target.value)} className="border rounded px-3 py-2 text-sm">
            <option value="">All countries</option>
            <option value="UK">GB — United Kingdom</option>
            <option value="US">US — United States</option>
            <option value="CA">CA — Canada</option>
            <option value="AU">AU — Australia</option>
            <option value="FR">FR — France</option>
            <option value="DE">DE — Germany</option>
          </select>
          <select value={sortBy} onChange={e => setSortBy(e.target.value as SortOption)} className="border rounded px-3 py-2 text-sm">
            <option value="recent">Most recent</option>
            <option value="oldest">Oldest</option>
            <option value="country">Country A-Z</option>
            <option value="units">Most units</option>
          </select>
        </div>
      </div>

      {showForm && (
        <div className="bg-white rounded-lg shadow p-4 mb-6">
          <div className="flex items-center gap-4">
            <select value={newCountry} onChange={e => setNewCountry(e.target.value)} className="border rounded px-3 py-2">
              <option value="UK">GB — United Kingdom</option>
              <option value="US">US — United States</option>
              <option value="CA">CA — Canada</option>
              <option value="AU">AU — Australia</option>
              <option value="FR">FR — France</option>
              <option value="DE">DE — Germany</option>
            </select>
            <button onClick={createShipment} disabled={creating} className="bg-green-600 text-white px-4 py-2 rounded text-sm hover:bg-green-700 disabled:opacity-60">
              {creating ? 'Creating...' : 'Create'}
            </button>
            <button onClick={() => { setShowForm(false); setCreateError('') }} className="text-gray-500 text-sm">Cancel</button>
          </div>
          {createError && <p className="mt-2 text-sm text-red-600">{createError}</p>}
        </div>
      )}

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Total Shipped</p>
            <p className="text-2xl font-bold">{(stats.shipped.total_units || 0).toLocaleString()}</p>
            <p className="text-xs text-gray-400">{stats.shipped.total_shipments || 0} shipments</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">In Progress</p>
            <p className="text-2xl font-bold text-blue-600">{(stats.in_progress.total_units || 0).toLocaleString()}</p>
            <p className="text-xs text-gray-400">{stats.in_progress.total_shipments || 0} shipments</p>
          </div>
          {stats.by_country.slice(0, 2).map(c => (
            <div key={c.country} className="bg-white rounded-lg shadow p-4">
              <p className="text-sm text-gray-500 flex items-center gap-1"><CountryBadge country={c.country} /> {c.country}</p>
              <p className="text-2xl font-bold">{(c.units || 0).toLocaleString()}</p>
              <p className="text-xs text-gray-400">{c.shipments} shipments</p>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── Left: shipment list ── */}
        <div>
          <h3 className="text-lg font-semibold mb-3">Shipment Log</h3>
          {loadError && (
            <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{loadError}</div>
          )}
          {loading ? (
            <p className="text-gray-400">Loading...</p>
          ) : sortedShipments.length === 0 ? (
            <p className="text-gray-400 text-sm">No shipments found.</p>
          ) : (
            <div className="space-y-2">
              {sortedShipments.map(s => (
                <div
                  key={s.id}
                  onClick={() => viewDetail(s.id)}
                  className={`bg-white rounded-lg shadow p-3 cursor-pointer hover:ring-2 hover:ring-blue-300 ${
                    selected?.id === s.id ? 'ring-2 ring-blue-500' : ''
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold">FBA-{s.id}</span>
                      <span className="text-sm font-medium flex items-center gap-1">
                        <CountryBadge country={s.country} /> {s.country}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${STATUS_COLOURS[s.status] || 'bg-gray-100'}`}>
                        {s.status}
                      </span>
                    </div>
                    <div className="text-sm text-gray-500">
                      {s.total_units} units / {s.item_count} items
                    </div>
                  </div>
                  <div className="text-xs text-gray-400 mt-1">{s.shipment_date || 'No date'}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Right: shipment detail ── */}
        <div>
          {selected && (
            <div className="bg-white rounded-lg shadow p-4">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-lg font-semibold">
                    FBA-{selected.id} — <CountryBadge country={selected.country} /> {selected.country}
                  </h3>
                  <p className="text-sm text-gray-500">
                    {selected.shipment_date || 'Unscheduled'} — {selected.total_units} units
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-1 rounded ${STATUS_COLOURS[selected.status]}`}>
                    {selected.status}
                  </span>
                  {selected.status !== 'shipped' && (
                    <>
                      <button
                        onClick={() => markShipped(selected.id)}
                        className="bg-green-600 text-white px-3 py-1 rounded text-xs hover:bg-green-700"
                      >
                        Mark Shipped
                      </button>
                      <button
                        onClick={() => setShowAddItems(!showAddItems)}
                        className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
                      >
                        {showAddItems ? 'Hide' : 'Add Items'}
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => setDeleteConfirm(selected.id)}
                    className="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {showAddItems && selected.status !== 'shipped' && (
                <AddItemsForm
                  shipmentId={selected.id}
                  onDone={() => viewDetail(selected.id)}
                />
              )}

              <table className="w-full text-sm mt-3">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2">M-Number</th>
                    <th className="text-left py-2">Description</th>
                    <th className="text-right py-2">Qty</th>
                    <th className="text-right py-2">Box</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.items.length === 0 ? (
                    <tr><td colSpan={4} className="py-4 text-center text-gray-400 text-sm">No items yet. Click "Add Items" above to add products to this shipment.</td></tr>
                  ) : (
                    selected.items.map(item => (
                      <tr key={item.id} className="border-b">
                        <td className="py-1.5 font-mono">{item.m_number}</td>
                        <td className="py-1.5 text-gray-600">{item.description}</td>
                        <td className="py-1.5 text-right">{item.quantity}</td>
                        <td className="py-1.5 text-right text-gray-400">{item.box_number || '-'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── Delete confirmation modal ── */}
      <ConfirmDialog
        open={deleteConfirm !== null}
        title="Delete Shipment"
        message={`Are you sure you want to delete shipment FBA-${deleteConfirm}? This action cannot be undone and will remove all items in the shipment.`}
        confirmLabel="Delete"
        danger
        onConfirm={() => deleteConfirm !== null && deleteShipment(deleteConfirm)}
        onCancel={() => setDeleteConfirm(null)}
      />
    </div>
  )
}
