'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { api } from '@/lib/api'

const INITIAL_VISIBLE = 100
const PAGE_SIZE = 100

interface AssemblyProduct {
  id: number
  m_number: string
  description: string
  blank: string
  material: string
  machine_type: string
  blank_family: string
}

const MACHINE_TYPE_OPTIONS = [
  { value: '', label: '— (auto)' },
  { value: 'UV', label: 'UV' },
  { value: 'SUB', label: 'SUB' },
]

const BLANK_FAMILY_OPTIONS = [
  { value: '', label: '— unassigned' },
  { value: 'A4s', label: "A4's (Stalin, Joseph, Fritzel)" },
  { value: 'A5s', label: "A5's (Saddam, Ted, Prince Andrew)" },
  { value: 'Dicks', label: "Dick's (Dick, Spotted Dick, Harry, Saville, Harvey)" },
  { value: 'Stakes', label: 'Stakes (Tom, Big Dick, Little Dick, Glitter, Kirsty)' },
  { value: 'Myras', label: "Myra's (Myra, Dorothea, Aileen)" },
  { value: 'Donalds', label: "Donald's (Idi, Donald, Dracula, Bundy)" },
  { value: 'Hanging', label: 'Hanging signs (Louis, Kim)' },
]

const BLANK_FAMILY_LABELS: Record<string, string> = {
  A4s: "A4's", A5s: "A5's", Dicks: "Dick's", Stakes: 'Stakes',
  Myras: "Myra's", Donalds: "Donald's", Hanging: 'Hanging signs',
}

export default function AssemblyPage() {
  const [products, setProducts] = useState<AssemblyProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [saving, setSaving] = useState<Record<number, boolean>>({})
  const [uniqueBlanks, setUniqueBlanks] = useState<string[]>([])
  const [uniqueMaterials, setUniqueMaterials] = useState<string[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE)
  const sentinelRef = useRef<HTMLTableRowElement | null>(null)

  useEffect(() => {
    api('/api/products/assemblies/')
      .then(r => r.json())
      .then((data: AssemblyProduct[]) => {
        setProducts(data)
        setUniqueBlanks(Array.from(new Set(data.map(p => p.blank?.trim()).filter(Boolean))).sort())
        setUniqueMaterials(Array.from(new Set(data.map(p => p.material?.trim()).filter(Boolean))).sort())
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const filtered = products.filter(p => {
    if (!search) return true
    const q = search.toLowerCase()
    return p.m_number.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)
  })

  // Reset windowing when the filtered list changes (e.g. search term)
  useEffect(() => {
    setVisibleCount(INITIAL_VISIBLE)
  }, [search])

  const visibleRows = filtered.slice(0, visibleCount)
  const hasMore = visibleCount < filtered.length

  // IntersectionObserver to load more rows when the sentinel scrolls into view
  useEffect(() => {
    if (!hasMore || loading) return
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      entries => {
        if (entries.some(e => e.isIntersecting)) {
          setVisibleCount(c => Math.min(c + PAGE_SIZE, filtered.length))
        }
      },
      { rootMargin: '400px' }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, loading, filtered.length, visibleCount])

  const toggleSelect = useCallback((id: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(() => {
    setSelected(prev =>
      prev.size === filtered.length ? new Set() : new Set(filtered.map(p => p.id))
    )
  }, [filtered])

  const patch = useCallback(async (id: number, field: keyof AssemblyProduct, value: string) => {
    // If this row is selected, apply to all selected; otherwise just this row
    const ids = selected.has(id) ? Array.from(selected) : [id]

    setSaving(prev => {
      const n = { ...prev }
      ids.forEach(i => { n[i] = true })
      return n
    })
    setProducts(prev => prev.map(p => ids.includes(p.id) ? { ...p, [field]: value } : p))

    try {
      await Promise.all(ids.map(targetId =>
        api(`/api/products/${targetId}/assembly/`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [field]: value }),
        })
      ))
    } catch {
      // Reload on error to revert
      api('/api/products/assemblies/')
        .then(r => r.json())
        .then((data: AssemblyProduct[]) => setProducts(data))
        .catch(() => {})
    }

    setSaving(prev => {
      const n = { ...prev }
      ids.forEach(i => { n[i] = false })
      return n
    })
  }, [selected])

  const allSelected = filtered.length > 0 && selected.size === filtered.length
  const someSelected = selected.size > 0 && !allSelected

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold">Assembly</h2>
          {selected.size > 0 && (
            <span className="text-sm bg-blue-100 text-blue-700 px-2 py-0.5 rounded font-medium">
              {selected.size} selected — changes will apply to all
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-400">
            {hasMore ? `${visibleCount} of ${filtered.length}` : `${filtered.length}`} products
          </span>
          <input
            type="text"
            placeholder="Search M-number or description..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="border rounded px-3 py-2 w-80 text-sm"
          />
        </div>
      </div>

      <p className="text-sm text-gray-500 mb-4">
        Set blank, material, machine type (UV/SUB), and blank family for each sign.
        Changes save instantly. Select multiple rows with the checkbox — changes to one will apply to all selected.
        Machine type set to <em>auto</em> derives UV/SUB from the blank name automatically.
      </p>

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full bg-white rounded-lg shadow text-sm">
            <thead>
              <tr className="border-b bg-gray-50 text-left">
                <th className="px-3 py-3 text-center w-10">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    ref={el => { if (el) el.indeterminate = someSelected }}
                    onChange={toggleSelectAll}
                    className="w-4 h-4 cursor-pointer accent-blue-600"
                    title="Select all"
                  />
                </th>
                <th className="px-4 py-3 font-medium text-gray-700 whitespace-nowrap">M-Number</th>
                <th className="px-4 py-3 font-medium text-gray-700">Description</th>
                <th className="px-4 py-3 font-medium text-gray-700">Blank</th>
                <th className="px-4 py-3 font-medium text-gray-700">Material</th>
                <th className="px-4 py-3 font-medium text-gray-700">Machine</th>
                <th className="px-4 py-3 font-medium text-gray-700">Blank Family</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">No products found.</td></tr>
              ) : visibleRows.map(p => {
                const isSelected = selected.has(p.id)
                return (
                  <tr
                    key={p.id}
                    className={`border-b hover:bg-gray-50 ${saving[p.id] ? 'opacity-60' : ''} ${isSelected ? 'bg-blue-50' : ''}`}
                  >
                    <td className="px-3 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(p.id)}
                        className="w-4 h-4 cursor-pointer accent-blue-600"
                      />
                    </td>
                    <td className="px-4 py-2 font-mono">{p.m_number}</td>
                    <td className="px-4 py-2 text-gray-700 max-w-xs truncate" title={p.description}>{p.description}</td>

                    {/* Blank */}
                    <td className="px-4 py-2">
                      <select
                        value={p.blank}
                        onChange={e => patch(p.id, 'blank', e.target.value)}
                        className="border rounded px-2 py-1 text-sm bg-white w-full max-w-[160px]"
                      >
                        {!uniqueBlanks.includes(p.blank?.trim()) && p.blank && (
                          <option value={p.blank}>{p.blank}</option>
                        )}
                        {uniqueBlanks.map(b => <option key={b} value={b}>{b}</option>)}
                      </select>
                    </td>

                    {/* Material */}
                    <td className="px-4 py-2">
                      <select
                        value={p.material}
                        onChange={e => patch(p.id, 'material', e.target.value)}
                        className="border rounded px-2 py-1 text-sm bg-white w-full max-w-[140px]"
                      >
                        <option value="">—</option>
                        {!uniqueMaterials.includes(p.material?.trim()) && p.material && (
                          <option value={p.material}>{p.material}</option>
                        )}
                        {uniqueMaterials.map(m => <option key={m} value={m}>{m}</option>)}
                      </select>
                    </td>

                    {/* Machine type */}
                    <td className="px-4 py-2">
                      <select
                        value={p.machine_type}
                        onChange={e => patch(p.id, 'machine_type', e.target.value)}
                        className="border rounded px-2 py-1 text-sm bg-white"
                      >
                        {MACHINE_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    </td>

                    {/* Blank family */}
                    <td className="px-4 py-2">
                      <select
                        value={p.blank_family}
                        onChange={e => patch(p.id, 'blank_family', e.target.value)}
                        className="border rounded px-2 py-1 text-sm bg-white w-full max-w-[200px]"
                      >
                        {BLANK_FAMILY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                      {p.blank_family && (
                        <span className="ml-1 text-xs text-gray-400">{BLANK_FAMILY_LABELS[p.blank_family]}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
              {hasMore && (
                <tr ref={sentinelRef}>
                  <td colSpan={7} className="px-4 py-4 text-center text-xs text-gray-400">
                    Loading more… ({visibleCount} of {filtered.length})
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
