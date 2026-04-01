'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

interface Product {
  id: number
  m_number: string
  description: string
  blank: string
  material: string
  active: boolean
  current_stock: number
  stock_deficit: number
}

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const params = new URLSearchParams({ search, page_size: '100' })
    api(`/api/products/?${params}`)
      .then(res => res.json())
      .then(data => {
        setProducts(data.results || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [search])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Products</h2>
        <input
          type="text"
          placeholder="Search M-number or description..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border rounded px-3 py-2 w-80"
        />
      </div>

      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : (
        <table className="w-full bg-white rounded-lg shadow text-sm">
          <thead>
            <tr className="border-b bg-gray-50">
              <th className="text-left px-4 py-3">M-Number</th>
              <th className="text-left px-4 py-3">Description</th>
              <th className="text-left px-4 py-3">Blank</th>
              <th className="text-left px-4 py-3">Material</th>
              <th className="text-right px-4 py-3">Stock</th>
              <th className="text-right px-4 py-3">Deficit</th>
            </tr>
          </thead>
          <tbody>
            {products.map(p => (
              <tr key={p.id} className="border-b hover:bg-gray-50">
                <td className="px-4 py-2 font-mono">{p.m_number}</td>
                <td className="px-4 py-2">{p.description}</td>
                <td className="px-4 py-2">{p.blank}</td>
                <td className="px-4 py-2">{p.material}</td>
                <td className="px-4 py-2 text-right">{p.current_stock}</td>
                <td className="px-4 py-2 text-right">
                  {p.stock_deficit > 0 ? (
                    <span className="text-red-600 font-semibold">{p.stock_deficit}</span>
                  ) : (
                    <span className="text-green-600">0</span>
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
