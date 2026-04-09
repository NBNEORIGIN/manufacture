'use client'

import { useEffect, useState, useCallback } from 'react'
import { api } from '@/lib/api'

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

  useEffect(() => {
    api('/api/products/assemblies/')
      .then(r => r.json())
      .then((data: AssemblyProduct[]) => {
        setProducts(data)
        setUniqueBlanks(Array.from(new Set(data.map(p => p.blank).filter(Boolean))).sort())
        setUniqueMaterials(Array.from(new Set(data.map(p => p.material).filter(Boolean))).sort())
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const patch = useCallback(async (id: number, field: keyof AssemblyProduct, value: string) => {
    setSaving(prev => ({ ...prev, [id]: true }))
    setProducts(prev => prev.map(p => p.id === id ? { ...p, [field]: value } : p))
    try {
      await api(`/api/products/${id}/assembly/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [field]: value }),
      })
    } catch {
      // Reload on error to revert
      api('/api/products/assemblies/')
        .then(r => r.json())
        .then((data: AssemblyProduct[]) => setProducts(data))
        .catch(() => {})
    }
    setSaving(prev => ({ ...prev, [id]: false }))
  }, [])

  const filtered = products.filter(p => {
    if (!search) return true
    const q = search.toLowerCase()
    return p.m_number.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Assembly</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-400">{filtered.length} products</span>
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
        Changes save instantly. Machine type set to <em>auto</em> derives UV/SUB from the blank name automatically.
      </p>

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full bg-white rounded-lg shadow text-sm">
            <thead>
              <tr className="border-b bg-gray-50 text-left">
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
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No products found.</td></tr>
              ) : filtered.map(p => (
                <tr key={p.id} className={`border-b hover:bg-gray-50 ${saving[p.id] ? 'opacity-60' : ''}`}>
                  <td className="px-4 py-2 font-mono">{p.m_number}</td>
                  <td className="px-4 py-2 text-gray-700 max-w-xs truncate" title={p.description}>{p.description}</td>

                  {/* Blank */}
                  <td className="px-4 py-2">
                    <select
                      value={p.blank}
                      onChange={e => patch(p.id, 'blank', e.target.value)}
                      className="border rounded px-2 py-1 text-sm bg-white w-full max-w-[160px]"
                    >
                      {!uniqueBlanks.includes(p.blank) && p.blank && (
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
                      {!uniqueMaterials.includes(p.material) && p.material && (
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
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
