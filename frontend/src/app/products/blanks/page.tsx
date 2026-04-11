'use client'

// /products/blanks — edit BlankType rows (name, dims, weight), link products,
// and push dims onto linked products via "Apply to products".
//
// Per-product overrides live on the main /products page (click the dims cell).

import { Fragment, useEffect, useState, useCallback } from 'react'
import { api } from '@/lib/api'

interface BlankType {
  id: number
  name: string
  length_cm: string  // DecimalField comes across as string
  width_cm: string
  height_cm: string
  weight_g: number
  notes: string
  product_count: number
}

interface UnassignedGroup {
  blank: string
  count: number
}

interface LinkedProduct {
  id: number
  m_number: string
  description: string
  blank: string
  shipping_dims_overridden: boolean
}

type Toast = { kind: 'ok' | 'err'; msg: string } | null

function blankDim(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

export default function BlanksPage() {
  const [blanks, setBlanks] = useState<BlankType[]>([])
  const [unassigned, setUnassigned] = useState<UnassignedGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [linkedCache, setLinkedCache] = useState<Record<number, LinkedProduct[]>>({})
  const [toast, setToast] = useState<Toast>(null)

  // New-row draft
  const [newRow, setNewRow] = useState({
    name: '', length_cm: '', width_cm: '', height_cm: '', weight_g: '',
  })

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [blanksRes, unRes] = await Promise.all([
        api('/api/blanks/'),
        api('/api/blanks/unassigned-products/'),
      ])
      const bList: BlankType[] = await blanksRes.json()
      const uList: UnassignedGroup[] = await unRes.json()
      setBlanks(Array.isArray(bList) ? bList : (bList as any).results ?? [])
      setUnassigned(uList)
    } catch {
      setToast({ kind: 'err', msg: 'Failed to load blanks' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const patchBlank = useCallback(async (id: number, field: keyof BlankType, value: string | number) => {
    try {
      const res = await api(`/api/blanks/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [field]: value }),
      })
      if (!res.ok) throw new Error('save failed')
      const updated: BlankType = await res.json()
      setBlanks(prev => prev.map(b => b.id === id ? { ...b, ...updated } : b))
    } catch {
      setToast({ kind: 'err', msg: `Failed to save ${String(field)}` })
      loadAll()
    }
  }, [loadAll])

  const createBlank = useCallback(async () => {
    if (!newRow.name.trim()) {
      setToast({ kind: 'err', msg: 'Name is required' })
      return
    }
    if (!newRow.length_cm || !newRow.width_cm || !newRow.height_cm || !newRow.weight_g) {
      setToast({ kind: 'err', msg: 'All dimensions + weight required' })
      return
    }
    try {
      const res = await api('/api/blanks/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newRow.name.trim(),
          length_cm: newRow.length_cm,
          width_cm: newRow.width_cm,
          height_cm: newRow.height_cm,
          weight_g: parseInt(newRow.weight_g, 10),
        }),
      })
      if (!res.ok) {
        const body = await res.text()
        throw new Error(body || 'create failed')
      }
      setNewRow({ name: '', length_cm: '', width_cm: '', height_cm: '', weight_g: '' })
      loadAll()
      setToast({ kind: 'ok', msg: 'Blank type created' })
    } catch (e: any) {
      setToast({ kind: 'err', msg: e.message || 'Create failed' })
    }
  }, [newRow, loadAll])

  const deleteBlank = useCallback(async (bt: BlankType) => {
    if (!confirm(`Delete blank type "${bt.name}"? Linked products will be unlinked (their shipping dims stay as-is).`)) return
    try {
      const res = await api(`/api/blanks/${bt.id}/`, { method: 'DELETE' })
      if (!res.ok) throw new Error('delete failed')
      setBlanks(prev => prev.filter(b => b.id !== bt.id))
      setToast({ kind: 'ok', msg: `Deleted ${bt.name}` })
      loadAll()
    } catch {
      setToast({ kind: 'err', msg: 'Delete failed' })
    }
  }, [loadAll])

  const applyToProducts = useCallback(async (bt: BlankType, force: boolean) => {
    const msg = force
      ? `Copy dims to ALL ${bt.product_count} linked product(s), OVERWRITING any manual overrides?`
      : `Copy dims to linked products (skipping those with manual overrides)?`
    if (!confirm(msg)) return
    try {
      const res = await api(`/api/blanks/${bt.id}/apply-to-products/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force }),
      })
      if (!res.ok) throw new Error('apply failed')
      const body = await res.json()
      setToast({ kind: 'ok', msg: `Applied to ${body.products_updated} product(s)` })
      if (expandedId === bt.id) loadLinked(bt.id)
    } catch {
      setToast({ kind: 'err', msg: 'Apply failed' })
    }
  }, [expandedId])

  const loadLinked = useCallback(async (id: number) => {
    try {
      const res = await api(`/api/blanks/${id}/products/`)
      const list: LinkedProduct[] = await res.json()
      setLinkedCache(prev => ({ ...prev, [id]: list }))
    } catch {
      setToast({ kind: 'err', msg: 'Failed to load linked products' })
    }
  }, [])

  const toggleExpand = useCallback((id: number) => {
    setExpandedId(prev => {
      if (prev === id) return null
      if (!linkedCache[id]) loadLinked(id)
      return id
    })
  }, [linkedCache, loadLinked])

  const linkByBlankMatch = useCallback(async (btId: number, blankString: string) => {
    if (!confirm(`Link all products where blank = "${blankString}" to this blank type?`)) return
    try {
      const res = await api(`/api/blanks/${btId}/link/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ match_blank: blankString }),
      })
      if (!res.ok) throw new Error('link failed')
      const body = await res.json()
      setToast({ kind: 'ok', msg: `Linked ${body.linked} product(s)` })
      loadAll()
      if (expandedId === btId) loadLinked(btId)
    } catch {
      setToast({ kind: 'err', msg: 'Link failed' })
    }
  }, [expandedId, loadAll, loadLinked])

  const unlinkOne = useCallback(async (btId: number, productId: number) => {
    try {
      const res = await api(`/api/blanks/${btId}/unlink/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_ids: [productId] }),
      })
      if (!res.ok) throw new Error('unlink failed')
      loadLinked(btId)
      loadAll()
    } catch {
      setToast({ kind: 'err', msg: 'Unlink failed' })
    }
  }, [loadAll, loadLinked])

  return (
    <div>
      <div className="flex gap-4 border-b mb-6">
        <a href="/products" className="px-4 py-2 text-gray-500 hover:text-blue-600 border-b-2 border-transparent">
          All Products
        </a>
        <a href="/products/blanks" className="px-4 py-2 font-semibold text-blue-600 border-b-2 border-blue-600">
          Blanks &amp; Shipping Dims
        </a>
      </div>

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Blank Types</h2>
        <p className="text-sm text-gray-500">
          Source of shipping dimensions for FBA packing. Apply to products after editing.
        </p>
      </div>

      {toast && (
        <div className={`mb-3 px-3 py-2 rounded text-sm ${
          toast.kind === 'ok' ? 'bg-green-50 border border-green-200 text-green-700'
                              : 'bg-red-50 border border-red-200 text-red-700'
        }`}>
          {toast.msg}
        </div>
      )}

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full bg-white rounded-lg shadow text-sm">
            <thead>
              <tr className="border-b bg-gray-50 text-left">
                <th className="px-4 py-3 w-10"></th>
                <th className="px-4 py-3 font-medium text-gray-700">Name</th>
                <th className="px-4 py-3 font-medium text-gray-700 text-right">L (cm)</th>
                <th className="px-4 py-3 font-medium text-gray-700 text-right">W (cm)</th>
                <th className="px-4 py-3 font-medium text-gray-700 text-right">H (cm)</th>
                <th className="px-4 py-3 font-medium text-gray-700 text-right">Weight (g)</th>
                <th className="px-4 py-3 font-medium text-gray-700 text-right"># linked</th>
                <th className="px-4 py-3 font-medium text-gray-700 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {blanks.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                  No blank types yet. Add one below.
                </td></tr>
              )}
              {blanks.map(bt => (
                <Fragment key={bt.id}>
                  <tr className="border-b hover:bg-gray-50">
                    <td className="px-4 py-2">
                      <button
                        onClick={() => toggleExpand(bt.id)}
                        className="text-gray-400 hover:text-gray-700"
                        title="Show linked products"
                      >
                        {expandedId === bt.id ? '▼' : '▶'}
                      </button>
                    </td>
                    <td className="px-4 py-2 font-mono">
                      <InlineEdit value={bt.name} onSave={v => patchBlank(bt.id, 'name', v)} />
                    </td>
                    <td className="px-4 py-2 text-right">
                      <InlineEdit value={blankDim(bt.length_cm)} numeric onSave={v => patchBlank(bt.id, 'length_cm', v)} />
                    </td>
                    <td className="px-4 py-2 text-right">
                      <InlineEdit value={blankDim(bt.width_cm)} numeric onSave={v => patchBlank(bt.id, 'width_cm', v)} />
                    </td>
                    <td className="px-4 py-2 text-right">
                      <InlineEdit value={blankDim(bt.height_cm)} numeric onSave={v => patchBlank(bt.id, 'height_cm', v)} />
                    </td>
                    <td className="px-4 py-2 text-right">
                      <InlineEdit value={String(bt.weight_g)} numeric onSave={v => patchBlank(bt.id, 'weight_g', parseInt(v, 10) || 0)} />
                    </td>
                    <td className="px-4 py-2 text-right text-gray-600">{bt.product_count}</td>
                    <td className="px-4 py-2 text-right whitespace-nowrap">
                      <button
                        onClick={() => applyToProducts(bt, false)}
                        className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
                        title="Copy dims to linked products, skipping manual overrides"
                      >
                        Apply
                      </button>
                      <button
                        onClick={() => applyToProducts(bt, true)}
                        className="ml-1 px-2 py-1 text-xs bg-orange-500 text-white rounded hover:bg-orange-600"
                        title="Copy dims to linked products, overwriting overrides"
                      >
                        Force
                      </button>
                      <button
                        onClick={() => deleteBlank(bt)}
                        className="ml-1 px-2 py-1 text-xs bg-red-500 text-white rounded hover:bg-red-600"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                  {expandedId === bt.id && (
                    <tr className="border-b bg-gray-50">
                      <td></td>
                      <td colSpan={7} className="px-4 py-3">
                        <LinkedProductsPanel
                          products={linkedCache[bt.id] || []}
                          onUnlink={id => unlinkOne(bt.id, id)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}

              {/* Create row */}
              <tr className="bg-blue-50 border-b">
                <td className="px-4 py-2 text-blue-600 text-center">+</td>
                <td className="px-4 py-2">
                  <input
                    className="w-full border rounded px-2 py-1 text-sm font-mono"
                    placeholder="SAVILLE"
                    value={newRow.name}
                    onChange={e => setNewRow({ ...newRow, name: e.target.value })}
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    className="w-20 border rounded px-2 py-1 text-sm text-right"
                    placeholder="0.0"
                    value={newRow.length_cm}
                    onChange={e => setNewRow({ ...newRow, length_cm: e.target.value })}
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    className="w-20 border rounded px-2 py-1 text-sm text-right"
                    placeholder="0.0"
                    value={newRow.width_cm}
                    onChange={e => setNewRow({ ...newRow, width_cm: e.target.value })}
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    className="w-20 border rounded px-2 py-1 text-sm text-right"
                    placeholder="0.0"
                    value={newRow.height_cm}
                    onChange={e => setNewRow({ ...newRow, height_cm: e.target.value })}
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    className="w-24 border rounded px-2 py-1 text-sm text-right"
                    placeholder="0"
                    value={newRow.weight_g}
                    onChange={e => setNewRow({ ...newRow, weight_g: e.target.value })}
                  />
                </td>
                <td></td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={createBlank}
                    className="px-3 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700"
                  >
                    Create
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Unassigned products panel */}
      <h3 className="mt-10 mb-3 text-lg font-semibold">Unassigned products ({unassigned.reduce((s, g) => s + g.count, 0)})</h3>
      <p className="text-sm text-gray-500 mb-3">
        Active products with no blank type linked, grouped by their raw <code>blank</code> field.
        Click a group to link all of them to an existing blank type at once.
      </p>
      {unassigned.length === 0 ? (
        <p className="text-gray-400 text-sm">All active products are linked to a blank type.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {unassigned.map(g => (
            <UnassignedChip
              key={g.blank || '(empty)'}
              group={g}
              blanks={blanks}
              onLink={(btId, blankStr) => linkByBlankMatch(btId, blankStr)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function InlineEdit({
  value, numeric = false, onSave,
}: { value: string; numeric?: boolean; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  useEffect(() => { setDraft(value) }, [value])

  if (!editing) {
    return (
      <span
        className="cursor-pointer hover:bg-blue-50 hover:text-blue-700 rounded px-1 py-0.5"
        onClick={() => setEditing(true)}
        title="Click to edit"
      >
        {value || '—'}
      </span>
    )
  }
  return (
    <input
      autoFocus
      type={numeric ? 'number' : 'text'}
      step={numeric ? '0.1' : undefined}
      value={draft}
      onChange={e => setDraft(e.target.value)}
      onBlur={() => { if (draft !== value) onSave(draft); setEditing(false) }}
      onKeyDown={e => {
        if (e.key === 'Enter') { if (draft !== value) onSave(draft); setEditing(false) }
        if (e.key === 'Escape') { setDraft(value); setEditing(false) }
      }}
      className={`border border-blue-400 rounded px-1 py-0.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 ${numeric ? 'w-20 text-right' : 'w-40'}`}
    />
  )
}

function LinkedProductsPanel({
  products, onUnlink,
}: { products: LinkedProduct[]; onUnlink: (productId: number) => void }) {
  if (products.length === 0) {
    return <p className="text-gray-500 text-sm">No products linked. Use "Unassigned products" below to link some.</p>
  }
  return (
    <div className="max-h-64 overflow-y-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-gray-500">
            <th className="py-1">M-Number</th>
            <th className="py-1">Description</th>
            <th className="py-1">Raw blank</th>
            <th className="py-1">Override?</th>
            <th className="py-1"></th>
          </tr>
        </thead>
        <tbody>
          {products.map(p => (
            <tr key={p.id} className="border-t">
              <td className="py-1 font-mono">{p.m_number}</td>
              <td className="py-1 truncate max-w-xs" title={p.description}>{p.description}</td>
              <td className="py-1 text-gray-500">{p.blank}</td>
              <td className="py-1">
                {p.shipping_dims_overridden && (
                  <span className="px-1.5 py-0.5 bg-yellow-100 text-yellow-800 rounded text-xs">manual</span>
                )}
              </td>
              <td className="py-1 text-right">
                <button
                  onClick={() => onUnlink(p.id)}
                  className="text-red-500 hover:text-red-700 text-xs"
                >
                  unlink
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function UnassignedChip({
  group, blanks, onLink,
}: {
  group: UnassignedGroup
  blanks: BlankType[]
  onLink: (btId: number, blankStr: string) => void
}) {
  const [open, setOpen] = useState(false)
  const label = group.blank || '(empty)'

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="px-2 py-1 bg-white border border-gray-300 rounded text-xs hover:border-blue-400"
      >
        <span className="font-mono">{label}</span>
        <span className="ml-1 text-gray-500">×{group.count}</span>
      </button>
      {open && (
        <div className="absolute z-10 mt-1 w-56 bg-white border border-gray-200 rounded shadow-lg py-1 max-h-64 overflow-y-auto">
          <div className="px-3 py-1 text-xs text-gray-500 border-b">Link to blank type:</div>
          {blanks.length === 0 ? (
            <div className="px-3 py-2 text-xs text-gray-400">No blank types exist yet.</div>
          ) : blanks.map(bt => (
            <button
              key={bt.id}
              onClick={() => { setOpen(false); onLink(bt.id, group.blank) }}
              className="w-full text-left px-3 py-1 text-xs hover:bg-blue-50"
            >
              <span className="font-mono">{bt.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
