'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

interface Material {
  id: number
  material_id: string
  name: string
  category: string
  unit_of_measure: string
  current_stock: number
  reorder_point: number
  standard_order_quantity: number
  preferred_supplier: string
  product_page_url: string
  lead_time_days: number
  safety_stock: number
  in_house_description: string
  current_price: number | null
  needs_reorder: boolean
}

interface Stats {
  total_materials: number
  needs_reorder: number
  total_stock_value: number
  categories: { category: string; count: number }[]
}

export default function MaterialsPage() {
  const [materials, setMaterials] = useState<Material[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [showReorderOnly, setShowReorderOnly] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams()
    if (showReorderOnly) params.set('needs_reorder', 'true')

    Promise.all([
      api(`/api/materials/?${params}`).then(r => r.json()),
      api('/api/materials/stats/').then(r => r.json()),
    ]).then(([data, statsData]) => {
      setMaterials(data.results || [])
      setStats(statsData)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [showReorderOnly])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Materials & Procurement</h2>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showReorderOnly}
            onChange={e => setShowReorderOnly(e.target.checked)}
          />
          Needs reorder only
        </label>
      </div>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Total Materials</p>
            <p className="text-2xl font-bold">{stats.total_materials}</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Needs Reorder</p>
            <p className="text-2xl font-bold text-red-600">{stats.needs_reorder}</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Stock Value</p>
            <p className="text-2xl font-bold">£{stats.total_stock_value.toFixed(2)}</p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Categories</p>
            <p className="text-2xl font-bold">{stats.categories.length}</p>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <table className="w-full bg-white rounded-lg shadow text-sm">
          <thead>
            <tr className="border-b bg-gray-50">
              <th className="text-left px-4 py-3">ID</th>
              <th className="text-left px-4 py-3">Name</th>
              <th className="text-left px-4 py-3">Category</th>
              <th className="text-right px-4 py-3">Stock</th>
              <th className="text-right px-4 py-3">Reorder At</th>
              <th className="text-right px-4 py-3">Order Qty</th>
              <th className="text-left px-4 py-3">Supplier</th>
              <th className="text-right px-4 py-3">Price</th>
              <th className="text-right px-4 py-3">Lead (days)</th>
              <th className="text-center px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {materials.map(m => (
              <tr key={m.id} className="border-b hover:bg-gray-50">
                <td className="px-4 py-2 font-mono">{m.material_id}</td>
                <td className="px-4 py-2">
                  {m.product_page_url ? (
                    <a href={m.product_page_url} target="_blank" rel="noopener" className="text-blue-600 hover:underline">
                      {m.name}
                    </a>
                  ) : m.name}
                </td>
                <td className="px-4 py-2 text-gray-500">{m.category}</td>
                <td className="px-4 py-2 text-right">{m.current_stock}</td>
                <td className="px-4 py-2 text-right text-gray-400">{m.reorder_point}</td>
                <td className="px-4 py-2 text-right">{m.standard_order_quantity || '-'}</td>
                <td className="px-4 py-2 text-gray-500">{m.preferred_supplier}</td>
                <td className="px-4 py-2 text-right">{m.current_price ? `£${m.current_price}` : '-'}</td>
                <td className="px-4 py-2 text-right">{m.lead_time_days || '-'}</td>
                <td className="px-4 py-2 text-center">
                  {m.needs_reorder ? (
                    <span className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded">Reorder</span>
                  ) : (
                    <span className="text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded">OK</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
