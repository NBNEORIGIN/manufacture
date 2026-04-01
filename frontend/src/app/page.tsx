'use client'

import { useEffect, useState } from 'react'

interface ApiStatus {
  app: string
  version: string
}

export default function Dashboard() {
  const [status, setStatus] = useState<ApiStatus | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/../')
      .then(res => res.json())
      .then(setStatus)
      .catch(() => setError('Backend not reachable'))
  }, [])

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Dashboard</h2>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-1">Backend Status</h3>
          {error ? (
            <p className="text-red-600">{error}</p>
          ) : status ? (
            <p className="text-green-600 font-semibold">{status.app} v{status.version}</p>
          ) : (
            <p className="text-gray-400">Loading...</p>
          )}
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-1">Quick Links</h3>
          <div className="space-y-2 mt-2">
            <a href="/make-list" className="block text-blue-600 hover:underline">View Make List</a>
            <a href="/products" className="block text-blue-600 hover:underline">Product Catalogue</a>
            <a href="/production" className="block text-blue-600 hover:underline">Production Orders</a>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-sm font-medium text-gray-500 mb-1">Phase 0</h3>
          <p className="text-gray-600 text-sm mt-2">
            Scaffolding complete. Seed data from Shipment Stock Sheet,
            then build the make list and production tracker.
          </p>
        </div>
      </div>
    </div>
  )
}
