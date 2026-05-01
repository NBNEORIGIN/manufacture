'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { api, downloadBarcodePdf } from '@/lib/api'
import HelpButton from '@/components/HelpButton'

/**
 * Ivan review #12 — Shipments major rework:
 *  1. Maximise shipment detail panel to cover whole screen
 *  2. Auto-populate from Restock Rec. Qty > 0 on create (backend)
 *  3. Manual add/remove items
 *  4. Machine column (STOCK / UV / SUB / empty)
 *  5. Status column (on_bench / in_process)
 *  6. Machine default = STOCK when stock >= required
 *  7. Red row when stock < required; machine default empty
 *  8. UV assignment notifies Ivan (backend)
 *  9. Print button for selected shipment
 * 10. "Take from Stock" input column (togglable)
 * 11. "Shipped" qty column (actual shipped)
 * 12. Box column (already exists)
 */

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
  product: number
  m_number: string
  description: string
  sku: string
  quantity: number
  quantity_shipped: number
  box_number: number | null
  machine_assignment: 'STOCK' | 'UV' | 'SUB' | ''
  stock_taken: number
  current_stock: number
  production_stage: 'printed' | 'heatpressed' | 'laminated' | 'on_bench' | ''
  item_notes: string
  blank_family: string
  // Ivan #20: inputs for the Simple column on shipment items.
  units_sold_90d: number
  fba_stock: number
  // Ivan #20: ProductBarcode id for the per-row print button. null if
  // no barcode is registered for this (product, marketplace).
  barcode_id: number | null
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

const STAGE_LABELS: Record<string, string> = {
  printed: 'Printed',
  heatpressed: 'Heatpressed',
  laminated: 'Laminated',
  on_bench: 'On bench',
}
const STAGE_BADGE: Record<string, string> = {
  printed: 'bg-blue-100 text-blue-800',
  heatpressed: 'bg-orange-100 text-orange-800',
  laminated: 'bg-purple-100 text-purple-800',
  on_bench: 'bg-green-100 text-green-800',
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

// ── Add items form (accepts M-number) ─────────────────────────────────────

function AddItemsForm({
  shipmentId, onDone,
}: { shipmentId: number; onDone: () => void }) {
  const [mNumber, setMNumber] = useState('')
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
            product: mNumber,
            quantity: Number(quantity),
            box_number: boxNumber ? Number(boxNumber) : null,
          }],
        }),
      })
      if (r.ok) {
        setMNumber('')
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
      <form onSubmit={submit} className="flex flex-wrap gap-2 items-end">
        <label className="text-xs">
          M-Number
          <input type="text" value={mNumber} onChange={e => setMNumber(e.target.value)} required placeholder="M0001" className="block border rounded px-2 py-1 w-24 font-mono" />
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

// ── Shipment detail panel ─────────────────────────────────────────────────

function machineTextColour(machine: string): React.CSSProperties {
  if (machine === 'STOCK') return { color: '#0a53a8', fontWeight: 700 }
  if (machine === 'SUB') return { color: '#2ac20e', fontWeight: 700 }
  if (machine === 'UV') return { color: '#5b9aab', fontWeight: 700 }
  return {}
}

// Ivan review #14: machine cell background colour
// STOCK → dark blue, SUB → green, UV → light blue-grey
// Ivan review #20: applied to the inner select/span only, NOT to the <td>,
// so the row's alternating green/yellow stripe still shows around the chip.
function machineBgStyle(machine: string): React.CSSProperties {
  if (machine === 'STOCK') return { backgroundColor: '#0a53a8', color: '#ffffff', fontWeight: 700 }
  if (machine === 'SUB') return { backgroundColor: '#2ac20e', color: '#ffffff', fontWeight: 700 }
  if (machine === 'UV') return { backgroundColor: '#c6dbe1', color: '#1a1a1a', fontWeight: 700 }
  return {}
}

// Ivan review #20: Simple metric — what the "old way" would recommend
// shipping for this SKU. Same formula the Restock tab uses.
function simpleQty(item: ShipmentItem): number {
  return Math.max(0, item.units_sold_90d - item.fba_stock)
}

function ShipmentDetailPanel({
  selected, onDelete, onReload, onMarkShipped, onClose,
  maximized, onToggleMaximize,
}: {
  selected: ShipmentDetail
  onDelete: () => void
  onReload: () => void
  onMarkShipped: () => void
  onClose: () => void
  maximized: boolean
  onToggleMaximize: () => void
}) {
  const [showAddItems, setShowAddItems] = useState(false)
  const [showTakeFromStock, setShowTakeFromStock] = useState(false)
  const [sortCol, setSortCol] = useState('')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  // Ivan review #14: per-column filters (maximized view only)
  const [fSku, setFSku] = useState('')
  const [fMNumber, setFMNumber] = useState('')
  const [fDescription, setFDescription] = useState('')
  const [fMachine, setFMachine] = useState('')
  const [fBlankFamily, setFBlankFamily] = useState('')

  // Reset filters when switching shipments
  useEffect(() => {
    setFSku(''); setFMNumber(''); setFDescription(''); setFMachine(''); setFBlankFamily('')
  }, [selected.id])

  const blankFamilies = Array.from(new Set(selected.items.map(i => i.blank_family).filter(Boolean))).sort()

  const filterItems = (items: ShipmentItem[]): ShipmentItem[] => {
    return items.filter(i => {
      if (fSku && !(i.sku || '').toLowerCase().includes(fSku.toLowerCase())) return false
      if (fMNumber && !(i.m_number || '').toLowerCase().includes(fMNumber.toLowerCase())) return false
      if (fDescription && !(i.description || '').toLowerCase().includes(fDescription.toLowerCase())) return false
      if (fMachine !== '') {
        if (fMachine === '__empty__' && i.machine_assignment !== '') return false
        if (fMachine !== '__empty__' && i.machine_assignment !== fMachine) return false
      }
      if (fBlankFamily && i.blank_family !== fBlankFamily) return false
      return true
    })
  }

  const handleSort = (col: string) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const sortItems = (items: ShipmentItem[]): ShipmentItem[] => {
    if (!sortCol) return items
    return [...items].sort((a, b) => {
      const mul = sortDir === 'asc' ? 1 : -1
      const av = (a as any)[sortCol] ?? ''
      const bv = (b as any)[sortCol] ?? ''
      if (typeof av === 'string' && typeof bv === 'string') return mul * av.localeCompare(bv)
      if (typeof av === 'number' && typeof bv === 'number') return mul * (av - bv)
      return 0
    })
  }

  const shipped = selected.status === 'shipped'

  // Ivan review #13 item 4: Stakes count
  const stakesCount = selected.items
    .filter(i => i.blank_family === 'Stakes')
    .reduce((sum, i) => sum + i.quantity, 0)

  // Patch a single item field
  const patchItem = async (itemId: number, patch: Partial<ShipmentItem>) => {
    const r = await api(`/api/shipment-items/${itemId}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      alert(d.error || `Update failed: ${r.status}`)
      return
    }
    onReload()
  }

  const deleteItem = async (itemId: number) => {
    if (!confirm('Remove this item from the shipment?')) return
    const r = await api(`/api/shipment-items/${itemId}/`, { method: 'DELETE' })
    if (!r.ok && r.status !== 204) {
      alert(`Delete failed: ${r.status}`)
      return
    }
    onReload()
  }

  const printShipment = () => {
    // Ivan review #12 item 9: print the shipment detail panel
    window.print()
  }

  // Ivan review #20: per-row "print barcode" button. Generates a thermal-roll
  // PDF with `quantity_shipped` copies of the SKU's barcode and triggers a
  // download — same path as the /barcodes "Print here" button. The agent
  // queue is intentionally bypassed; staff are at the workbench PC where the
  // thermal printer is plugged in, and the OS print dialog handles routing.
  const printItemBarcode = async (item: ShipmentItem) => {
    if (!item.barcode_id) {
      alert(`No barcode registered for ${item.m_number} in this marketplace`)
      return
    }
    if (item.quantity_shipped < 1) {
      alert(`Set "Shipped" qty before printing for ${item.m_number}`)
      return
    }
    try {
      await downloadBarcodePdf(
        [{ barcode_id: item.barcode_id, quantity: item.quantity_shipped }],
        'roll',
      )
    } catch {
      alert(`Failed to generate label PDF for ${item.m_number}`)
    }
  }

  return (
    <div
      id="shipment-print-area"
      className={
        maximized
          ? 'fixed inset-0 z-40 bg-white p-4 overflow-auto'
          : 'bg-white rounded-lg shadow p-4'
      }
    >
      <div className="flex items-center justify-between mb-4 no-print-hide">
        <div>
          <h3 className="text-lg font-semibold">
            FBA-{selected.id} — <CountryBadge country={selected.country} /> {selected.country}
          </h3>
          <p className="text-sm text-gray-500">
            {selected.shipment_date || 'Unscheduled'} — {selected.total_units} units
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap no-print">
          <span className={`text-xs px-2 py-1 rounded ${STATUS_COLOURS[selected.status]}`}>
            {selected.status}
          </span>
          <button
            onClick={() => setShowTakeFromStock(v => !v)}
            className="bg-gray-200 text-gray-800 px-3 py-1 rounded text-xs hover:bg-gray-300"
            title="Show/hide the Take-from-Stock column"
          >
            {showTakeFromStock ? 'Hide Take-Stock' : 'Show Take-Stock'}
          </button>
          <button
            onClick={printShipment}
            className="bg-gray-200 text-gray-800 px-3 py-1 rounded text-xs hover:bg-gray-300"
          >
            Print
          </button>
          <button
            onClick={onToggleMaximize}
            className="bg-gray-200 text-gray-800 px-3 py-1 rounded text-xs hover:bg-gray-300"
            title={maximized ? 'Shrink to side panel' : 'Fill screen'}
          >
            {maximized ? 'Restore' : 'Maximize'}
          </button>
          {!shipped && (
            <>
              <button onClick={onMarkShipped} className="bg-green-600 text-white px-3 py-1 rounded text-xs hover:bg-green-700">
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
          <button onClick={onDelete} className="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700">
            Delete
          </button>
          {maximized && (
            <button onClick={onClose} className="bg-gray-300 text-gray-900 px-3 py-1 rounded text-xs hover:bg-gray-400">
              Close
            </button>
          )}
        </div>
      </div>

      {showAddItems && !shipped && (
        <AddItemsForm shipmentId={selected.id} onDone={() => { onReload(); setShowAddItems(false) }} />
      )}

      {/* Stakes banner (Ivan review #13 item 4) */}
      {stakesCount > 0 && (
        <div className="mt-2 px-3 py-1.5 bg-yellow-100 border border-yellow-300 rounded text-sm font-medium text-yellow-800">
          Stakes — {stakesCount}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm mt-3 grid-cells">
          <thead>
            {(() => {
              // Copy a column's values for every visible row to the clipboard,
              // newline-separated. Lets Ivan paste a single column straight
              // into Excel — workaround for browsers selecting row-first.
              const copyColumn = (col: string) => {
                const items = sortItems(selected.items)
                const values = items.map(i => {
                  const v = (i as any)[col]
                  return v == null ? '' : String(v)
                })
                const text = values.join('\n')
                if (navigator.clipboard?.writeText) {
                  navigator.clipboard.writeText(text)
                }
              }

              const SH = ({ col, label, className = '' }: { col: string; label: string; className?: string }) => (
                <th className={`px-2 py-2 select-none ${className}`}>
                  <span
                    className="cursor-pointer hover:underline"
                    onClick={() => handleSort(col)}
                  >
                    {label} {sortCol === col ? (sortDir === 'asc' ? '▲' : '▼') : <span className="text-gray-300 text-xs">↕</span>}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); copyColumn(col) }}
                    title={`Copy this column to clipboard`}
                    className="ml-1.5 text-gray-300 hover:text-gray-700 text-xs no-print"
                    aria-label={`Copy ${label} column`}
                  >
                    ⧉
                  </button>
                </th>
              )
              return (<>
                <tr className="border-b bg-gray-50 text-left">
                  {maximized ? (
                    <>
                      <SH col="sku" label="SKU" className="print-hide-col" />
                      <SH col="m_number" label="M#" />
                      <th className="px-2 py-2">Notes</th>
                      <SH col="description" label="Description" />
                      {/* Ivan #20: tighter widths on Machine/Req/Stock/Shipped */}
                      <SH col="machine_assignment" label="Machine" className="w-20" />
                      <SH col="quantity" label="Req." className="text-right w-14" />
                      <SH col="current_stock" label="Stock" className="text-right w-14" />
                      {/* Ivan #20: Simple = max(0, 90d sales − FBA stock). The "old way" for sanity-check. */}
                      <SH col="simple_qty" label="Simple" className="text-right w-14 print-hide-col" />
                      {showTakeFromStock && <SH col="stock_taken" label="Take-Stock" className="text-right" />}
                      <SH col="quantity_shipped" label="Shipped" className="text-right w-14 print-hide-col" />
                      <SH col="box_number" label="Box" className="text-right print-hide-col" />
                      {/* Ivan #20: per-row Print barcode column */}
                      <th className="px-2 py-2 w-10 no-print" title="Print barcode (qty = Shipped)">🖨</th>
                      {!shipped && <th className="px-2 py-2 no-print"></th>}
                    </>
                  ) : (
                    <>
                      <SH col="m_number" label="M#" />
                      <SH col="description" label="Description" />
                      <SH col="quantity" label="Req." className="text-right w-14" />
                      <SH col="current_stock" label="Stock" className="text-right w-14" />
                      <SH col="machine_assignment" label="Machine" className="w-20" />
                      {!shipped && <th className="px-2 py-2 no-print"></th>}
                    </>
                  )}
                </tr>
                {maximized && (
                  <tr className="border-b bg-white text-left no-print">
                    <th className="px-2 py-1">
                      <input type="text" value={fSku} onChange={e => setFSku(e.target.value)} placeholder="filter…" className="w-full border border-gray-300 rounded px-1 py-0.5 text-xs font-normal" />
                    </th>
                    <th className="px-2 py-1">
                      <input type="text" value={fMNumber} onChange={e => setFMNumber(e.target.value)} placeholder="filter…" className="w-full border border-gray-300 rounded px-1 py-0.5 text-xs font-normal font-mono" />
                    </th>
                    <th className="px-2 py-1">
                      <select value={fBlankFamily} onChange={e => setFBlankFamily(e.target.value)} className="w-full border border-gray-300 rounded px-1 py-0.5 text-xs font-normal bg-white" title="Filter by blank family">
                        <option value="">All blanks</option>
                        {blankFamilies.map(b => <option key={b} value={b}>{b}</option>)}
                      </select>
                    </th>
                    <th className="px-2 py-1">
                      <input type="text" value={fDescription} onChange={e => setFDescription(e.target.value)} placeholder="filter…" className="w-full border border-gray-300 rounded px-1 py-0.5 text-xs font-normal" />
                    </th>
                    <th className="px-2 py-1">
                      <select value={fMachine} onChange={e => setFMachine(e.target.value)} className="w-full border border-gray-300 rounded px-1 py-0.5 text-xs font-normal bg-white">
                        <option value="">All</option>
                        <option value="STOCK">STOCK</option>
                        <option value="UV">UV</option>
                        <option value="SUB">SUB</option>
                        <option value="__empty__">(empty)</option>
                      </select>
                    </th>
                    <th className="px-2 py-1"></th>{/* Req. */}
                    <th className="px-2 py-1"></th>{/* Stock */}
                    <th className="px-2 py-1"></th>{/* Simple */}
                    {showTakeFromStock && <th className="px-2 py-1"></th>}
                    <th className="px-2 py-1"></th>{/* Shipped */}
                    <th className="px-2 py-1"></th>{/* Box */}
                    <th className="px-2 py-1"></th>{/* Print */}
                    {!shipped && <th className="px-2 py-1"></th>}
                  </tr>
                )}
              </>)
            })()}
          </thead>
          <tbody>
            {selected.items.length === 0 ? (
              <tr><td colSpan={maximized ? 11 : 6} className="py-4 text-center text-gray-400 text-sm">
                No items. New shipments auto-populate from Restock; use &quot;Add Items&quot; to add more.
              </td></tr>
            ) : (
              sortItems(maximized ? filterItems(selected.items) : selected.items).map((item, idx) => {
                const short = item.quantity > item.current_stock
                return (
                  <ItemRow
                    key={item.id}
                    item={item}
                    index={idx}
                    shipped={shipped}
                    shortStock={short}
                    showTakeFromStock={showTakeFromStock}
                    maximized={maximized}
                    onPatch={patch => patchItem(item.id, patch)}
                    onDelete={() => deleteItem(item.id)}
                    onPrint={printItemBarcode}
                  />
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Individual item row with inline editing ──────────────────────────────

function ItemRow({
  item, index, shipped, shortStock, showTakeFromStock, maximized, onPatch, onDelete, onPrint,
}: {
  item: ShipmentItem
  index: number
  shipped: boolean
  shortStock: boolean
  showTakeFromStock: boolean
  maximized: boolean
  onPatch: (patch: Partial<ShipmentItem>) => void
  onDelete: () => void
  onPrint: (item: ShipmentItem) => void
}) {
  const [takeStockDraft, setTakeStockDraft] = useState(String(item.stock_taken))
  const [shippedDraft, setShippedDraft] = useState(String(item.quantity_shipped))
  const [boxDraft, setBoxDraft] = useState(item.box_number == null ? '' : String(item.box_number))
  const [notesDraft, setNotesDraft] = useState(item.item_notes || '')

  useEffect(() => { setTakeStockDraft(String(item.stock_taken)) }, [item.stock_taken])
  useEffect(() => { setShippedDraft(String(item.quantity_shipped)) }, [item.quantity_shipped])
  useEffect(() => { setBoxDraft(item.box_number == null ? '' : String(item.box_number)) }, [item.box_number])
  useEffect(() => { setNotesDraft(item.item_notes || '') }, [item.item_notes])

  const commitTakeStock = () => {
    const v = parseInt(takeStockDraft, 10)
    if (isNaN(v) || v < 0) { setTakeStockDraft(String(item.stock_taken)); return }
    if (v !== item.stock_taken) onPatch({ stock_taken: v })
  }
  const commitShipped = () => {
    const v = parseInt(shippedDraft, 10)
    if (isNaN(v) || v < 0) { setShippedDraft(String(item.quantity_shipped)); return }
    if (v !== item.quantity_shipped) onPatch({ quantity_shipped: v })
  }
  const commitBox = () => {
    if (boxDraft === '') {
      if (item.box_number != null) onPatch({ box_number: null as any })
      return
    }
    const v = parseInt(boxDraft, 10)
    if (isNaN(v) || v < 0) { setBoxDraft(item.box_number == null ? '' : String(item.box_number)); return }
    if (v !== item.box_number) onPatch({ box_number: v })
  }
  const commitNotes = () => {
    if (notesDraft !== (item.item_notes || '')) onPatch({ item_notes: notesDraft } as any)
  }

  const rowStyle = { backgroundColor: index % 2 === 0 ? '#d9ead3' : '#fff2cc' }

  // ── Minimized: M#, Description, Req., Stock, Machine ──
  if (!maximized) {
    return (
      <tr className="border-b" style={rowStyle}>
        <td className="px-2 py-1.5 font-mono font-bold">{item.m_number}</td>
        <td className="px-2 py-1.5 text-gray-600 max-w-[200px] truncate" title={item.description}>{item.description}</td>
        <td className={`px-2 py-1.5 text-right ${shortStock ? 'text-red-600 font-semibold' : ''}`}>{item.quantity}</td>
        <td className="px-2 py-1.5 text-right text-gray-700">{item.current_stock}</td>
        <td className="px-2 py-1.5">
          {shipped ? (
            <span className="text-xs px-1.5 py-0.5 rounded" style={machineBgStyle(item.machine_assignment)}>{item.machine_assignment || '—'}</span>
          ) : (
            <select value={item.machine_assignment} onChange={e => onPatch({ machine_assignment: e.target.value as any })} className="border rounded px-1 py-0.5 text-xs" style={machineBgStyle(item.machine_assignment)}>
              <option value="">—</option>
              <option value="STOCK">STOCK</option>
              <option value="UV">UV</option>
              <option value="SUB">SUB</option>
            </select>
          )}
        </td>
        {!shipped && (
          <td className="px-2 py-1.5 text-right no-print">
            <button onClick={onDelete} className="text-red-500 hover:text-red-700 text-xs" title="Remove item">x</button>
          </td>
        )}
      </tr>
    )
  }

  // ── Maximized: SKU, M#, Notes, Description, Machine, Req., Stock, Take-Stock, Shipped, Box ──
  return (
    <tr className="border-b" style={rowStyle}>
      <td className="px-2 py-1.5 text-xs text-gray-600 font-mono max-w-[90px] truncate print-hide-col" title={item.sku}>{item.sku || '—'}</td>
      <td className="px-2 py-1.5 font-mono font-bold whitespace-nowrap">{item.m_number}</td>
      <td className="px-2 py-1.5">
        {shipped ? (
          <span className="text-xs text-gray-600">{item.item_notes || '—'}</span>
        ) : (
          <input
            type="text"
            value={notesDraft}
            data-empty={notesDraft.trim() === '' ? 'true' : 'false'}
            onChange={e => setNotesDraft(e.target.value)}
            onBlur={commitNotes}
            onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            className="w-32 border border-gray-300 rounded px-1 py-0.5 text-xs"
            placeholder="notes"
          />
        )}
      </td>
      <td className="px-2 py-1.5 text-gray-600 max-w-[200px] truncate" title={item.description}>{item.description}</td>
      {/* Ivan #20: cell stays neutral; the chip / select inside carries the machine colour */}
      <td className="px-2 py-1.5">
        {shipped ? (
          <span className="text-xs inline-block px-1.5 py-0.5 rounded" style={machineBgStyle(item.machine_assignment)}>{item.machine_assignment || '—'}</span>
        ) : (
          <select value={item.machine_assignment} onChange={e => onPatch({ machine_assignment: e.target.value as any })} className="border rounded px-1 py-0.5 text-xs" style={machineBgStyle(item.machine_assignment)}>
            <option value="">—</option>
            <option value="STOCK">STOCK</option>
            <option value="UV">UV</option>
            <option value="SUB">SUB</option>
          </select>
        )}
      </td>
      <td className={`px-2 py-1.5 text-right w-14 ${shortStock ? 'text-red-600 font-semibold' : ''}`}>{item.quantity}</td>
      <td className="px-2 py-1.5 text-right w-14 text-gray-700">{item.current_stock}</td>
      {/* Ivan #20: Simple metric — for sanity-check vs Required. */}
      <td
        className="px-2 py-1.5 text-right w-14 text-gray-700 print-hide-col"
        title={`Simple = max(0, ${item.units_sold_90d} sold last 90d − ${item.fba_stock} at FBA) = ${simpleQty(item)}`}
      >
        {simpleQty(item)}
      </td>
      {showTakeFromStock && (
        <td className="px-2 py-1.5 text-right">
          {shipped ? item.stock_taken : (
            <input type="number" min="0" value={takeStockDraft} onChange={e => setTakeStockDraft(e.target.value)} onBlur={commitTakeStock} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} className="w-16 text-right border border-gray-300 rounded px-1 py-0.5 text-xs" title="Take from stock" />
          )}
        </td>
      )}
      <td className="px-2 py-1.5 text-right w-14 print-hide-col">
        {shipped ? item.quantity_shipped : (
          <input type="number" min="0" value={shippedDraft} onChange={e => setShippedDraft(e.target.value)} onBlur={commitShipped} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} className="w-12 text-right border border-gray-300 rounded px-1 py-0.5 text-xs" title="Actual shipped" />
        )}
      </td>
      <td className="px-2 py-1.5 text-right print-hide-col">
        {shipped ? (item.box_number ?? '-') : (
          <input type="number" min="1" value={boxDraft} onChange={e => setBoxDraft(e.target.value)} onBlur={commitBox} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} className="w-14 text-right border border-gray-300 rounded px-1 py-0.5 text-xs" placeholder="-" />
        )}
      </td>
      {/* Ivan #20: per-row print barcode. Quantity = Shipped value. */}
      <td className="px-1 py-1.5 text-center w-10 no-print">
        <button
          onClick={() => onPrint(item)}
          disabled={!item.barcode_id || item.quantity_shipped < 1}
          title={
            !item.barcode_id ? `No barcode registered for ${item.m_number} in this marketplace` :
            item.quantity_shipped < 1 ? 'Set "Shipped" qty before printing' :
            `Print ${item.quantity_shipped} barcode${item.quantity_shipped === 1 ? '' : 's'} for ${item.m_number}`
          }
          className="text-base hover:opacity-80 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          🖨
        </button>
      </td>
      {!shipped && (
        <td className="px-2 py-1.5 text-right no-print">
          <button onClick={onDelete} className="text-red-500 hover:text-red-700 text-xs" title="Remove item">x</button>
        </td>
      )}
    </tr>
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
  const [maximized, setMaximized] = useState(false)

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
  }

  const reloadSelected = async () => {
    if (!selected) return
    await viewDetail(selected.id)
    loadShipments()
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
        const data = await res.json()
        setShowForm(false)
        setMessage(`Shipment created (${data.item_count || 0} items auto-added from Restock)`)
        setNewCountry('UK')
        loadShipments()
        if (data.id) await viewDetail(data.id)
        setTimeout(() => setMessage(''), 5000)
      } else {
        const data = await res.json().catch(() => ({}))
        setCreateError(data.detail || data.error || `Error ${res.status}`)
      }
    } catch {
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
      <div className="flex items-center justify-between mb-6 no-print">
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
        <div className="bg-white rounded-lg shadow p-4 mb-6 no-print">
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
              {creating ? 'Creating…' : 'Create'}
            </button>
            <button onClick={() => { setShowForm(false); setCreateError('') }} className="text-gray-500 text-sm">Cancel</button>
            <span className="text-xs text-gray-500">New shipments auto-populate with Restock items (Rec. Qty &gt; 0) for this country.</span>
          </div>
          {createError && <p className="mt-2 text-sm text-red-600">{createError}</p>}
        </div>
      )}

      {stats && !maximized && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6 no-print">
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

      <div className={maximized ? '' : 'grid grid-cols-1 lg:grid-cols-2 gap-6'}>
        {/* ── Left: shipment list (hidden when maximized) ── */}
        {!maximized && (
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
        )}

        {/* ── Right: shipment detail (or full-screen when maximized) ── */}
        <div>
          {selected && (
            <ShipmentDetailPanel
              selected={selected}
              maximized={maximized}
              onToggleMaximize={() => setMaximized(m => !m)}
              onClose={() => { setMaximized(false); setSelected(null) }}
              onDelete={() => setDeleteConfirm(selected.id)}
              onReload={reloadSelected}
              onMarkShipped={() => markShipped(selected.id)}
            />
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
