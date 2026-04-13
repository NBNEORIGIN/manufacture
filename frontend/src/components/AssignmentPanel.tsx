'use client'

import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'

/**
 * Dashboard assignment table (Ivan review #8, item 2).
 *
 * "Add a small table on the bottom of dashboard tab where you can
 * choose a sign, and person who will be assigned to make it. This
 * table is temporary and we will get rid of it, or remake it."
 *
 * Shows recent assignments + a form to create new ones.
 */

interface User { id: number; username: string }
interface Assignment {
  id: number; m_number: string; description: string
  assigned_to_username: string; assigned_by_username: string
  quantity: number; notes: string; status: string; created_at: string
}

export default function AssignmentPanel() {
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [productId, setProductId] = useState('')
  const [userId, setUserId] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    try {
      const [a, u] = await Promise.all([
        api('/api/assignments/?page_size=10').then(r => r.json()),
        api('/api/auth/me/').then(async r => {
          // We don't have a users list endpoint. Workaround: use the
          // assignments themselves to discover known users, or just
          // let the admin type a user ID. For MVP we'll do user ID.
          return r.json()
        }),
      ])
      setAssignments(a.results ?? a)
    } catch { /* silent */ }
  }, [])

  useEffect(() => { load() }, [load])

  const assign = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setMsg('')
    try {
      const r = await api('/api/assignments/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product: Number(productId),
          assigned_to: Number(userId),
          quantity: Number(quantity),
          notes,
        }),
      })
      if (r.ok) {
        setProductId('')
        setUserId('')
        setQuantity('1')
        setNotes('')
        setMsg('Assigned')
        setTimeout(() => setMsg(''), 3000)
        load()
      } else {
        const d = await r.json().catch(() => ({}))
        setMsg(`Error: ${d.detail || d.error || r.status}`)
      }
    } catch {
      setMsg('Network error')
    } finally {
      setBusy(false)
    }
  }

  const cancel = async (id: number) => {
    await api(`/api/assignments/${id}/`, { method: 'DELETE' })
    load()
  }

  return (
    <div className="mt-8 border rounded-lg p-4 bg-gray-50">
      <h3 className="text-sm font-bold text-gray-700 mb-2">
        Assign Job
        <span className="text-xs font-normal text-gray-400 ml-2">(temporary debug tool)</span>
      </h3>
      <form onSubmit={assign} className="flex flex-wrap gap-2 items-end mb-3">
        <label className="text-xs">
          Product ID
          <input type="number" value={productId} onChange={e => setProductId(e.target.value)} required className="block border rounded px-2 py-1 w-24" />
        </label>
        <label className="text-xs">
          User ID
          <input type="number" value={userId} onChange={e => setUserId(e.target.value)} required className="block border rounded px-2 py-1 w-20" />
        </label>
        <label className="text-xs">
          Qty
          <input type="number" min="1" value={quantity} onChange={e => setQuantity(e.target.value)} required className="block border rounded px-2 py-1 w-16" />
        </label>
        <label className="text-xs flex-1 min-w-[100px]">
          Notes
          <input type="text" value={notes} onChange={e => setNotes(e.target.value)} className="block border rounded px-2 py-1 w-full" placeholder="optional" />
        </label>
        <button type="submit" disabled={busy} className="px-3 py-1 bg-blue-600 text-white rounded text-xs disabled:opacity-50">
          {busy ? 'Assigning...' : 'Assign'}
        </button>
        {msg && <span className="text-xs text-green-600">{msg}</span>}
      </form>

      {assignments.length > 0 && (
        <table className="w-full text-xs">
          <thead className="text-left text-gray-500">
            <tr>
              <th className="py-1">M#</th>
              <th>Description</th>
              <th>Assigned to</th>
              <th>By</th>
              <th className="text-right">Qty</th>
              <th>Status</th>
              <th>When</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {assignments.map(a => (
              <tr key={a.id} className="border-t">
                <td className="py-1 font-mono font-bold">{a.m_number}</td>
                <td className="truncate max-w-[150px]">{a.description}</td>
                <td>{a.assigned_to_username}</td>
                <td className="text-gray-400">{a.assigned_by_username || '—'}</td>
                <td className="text-right">{a.quantity}</td>
                <td>
                  <span className={`px-1 py-0.5 rounded text-[10px] ${
                    a.status === 'completed' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
                  }`}>
                    {a.status}
                  </span>
                </td>
                <td className="text-gray-400">{new Date(a.created_at).toLocaleDateString('en-GB')}</td>
                <td>
                  {a.status === 'pending' && (
                    <button onClick={() => cancel(a.id)} className="text-red-500 hover:text-red-700">x</button>
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
