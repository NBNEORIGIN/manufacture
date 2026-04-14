'use client'

import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'

/**
 * Multi-step threaded job creator + display (Ivan review #10, item 5).
 *
 * Reddit-style thread display: each step shows the assigned user with
 * connecting arrows. Active step highlighted, completed steps greyed.
 *
 * Create form lets you add steps one at a time, each assigned to a
 * user from the dropdown, with a description of what they need to do.
 */

interface UserOption { id: number; display_name: string }

interface Step {
  id: number; step_number: number; assigned_to: number
  assigned_to_name: string; description: string; status: string
  completed_at: string | null; completed_by_name: string
}

interface JobItem {
  id: number; m_number: string; description: string
  created_by_name: string; title: string; notes: string
  status: string; steps: Step[]; step_chain: string; created_at: string
}

export default function JobThreadPanel() {
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [users, setUsers] = useState<UserOption[]>([])
  const [expanded, setExpanded] = useState<number | null>(null)

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [mNumber, setMNumber] = useState('')
  const [title, setTitle] = useState('')
  const [notes, setNotes] = useState('')
  const [newSteps, setNewSteps] = useState<Array<{ assigned_to: string; description: string }>>([
    { assigned_to: '', description: '' },
  ])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    try {
      const [j, u] = await Promise.all([
        api('/api/jobs/?page_size=20').then(r => r.json()),
        api('/api/auth/users/').then(r => r.json()),
      ])
      setJobs(j.results ?? j)
      const userList = u.users ?? []
      setUsers(userList)
      if (newSteps[0].assigned_to === '' && userList.length > 0) {
        setNewSteps([{ assigned_to: String(userList[0].id), description: '' }])
      }
    } catch { /* silent */ }
  }, [])

  useEffect(() => { load() }, [load])

  const addStep = () => {
    const defaultUser = users.length > 0 ? String(users[0].id) : ''
    setNewSteps([...newSteps, { assigned_to: defaultUser, description: '' }])
  }

  const removeStep = (i: number) => {
    if (newSteps.length <= 1) return
    setNewSteps(newSteps.filter((_, idx) => idx !== i))
  }

  const updateStep = (i: number, field: 'assigned_to' | 'description', val: string) => {
    const copy = [...newSteps]
    copy[i] = { ...copy[i], [field]: val }
    setNewSteps(copy)
  }

  const createJob = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setMsg('')
    try {
      const r = await api('/api/jobs/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          m_number_input: mNumber,
          title,
          notes,
          steps_input: newSteps.map(s => ({
            assigned_to: Number(s.assigned_to),
            description: s.description,
          })),
        }),
      })
      if (r.ok) {
        setMNumber('')
        setTitle('')
        setNotes('')
        const defUser = users.length > 0 ? String(users[0].id) : ''
        setNewSteps([{ assigned_to: defUser, description: '' }])
        setShowCreate(false)
        setMsg('Job created')
        setTimeout(() => setMsg(''), 3000)
        load()
      } else {
        const d = await r.json().catch(() => ({}))
        setMsg(`Error: ${JSON.stringify(d)}`)
      }
    } catch {
      setMsg('Network error')
    } finally {
      setBusy(false)
    }
  }

  const removeJob = async (id: number) => {
    await api(`/api/jobs/${id}/`, { method: 'DELETE' })
    load()
  }

  const completeStep = async (jobId: number, stepNumber: number) => {
    const r = await api(`/api/jobs/${jobId}/steps/${stepNumber}/complete/`, { method: 'POST' })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      alert(d.error || `Failed: ${r.status}`)
      return
    }
    load()
  }

  return (
    <div className="mt-6 border rounded-lg p-4 bg-white">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-gray-700">Threaded Jobs</h3>
        <div className="flex items-center gap-2">
          {msg && <span className={`text-xs ${msg.startsWith('Error') ? 'text-red-600' : 'text-green-600'}`}>{msg}</span>}
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="px-3 py-1 bg-blue-600 text-white rounded text-xs hover:bg-blue-700"
          >
            {showCreate ? 'Cancel' : 'New Job'}
          </button>
        </div>
      </div>

      {/* ── Create form ── */}
      {showCreate && (
        <form onSubmit={createJob} className="mb-4 p-3 bg-gray-50 rounded border space-y-2">
          <div className="flex flex-wrap gap-2">
            <label className="text-xs">
              M-Number
              <input type="text" value={mNumber} onChange={e => setMNumber(e.target.value)} required placeholder="M0001" className="block border rounded px-2 py-1 w-24 font-mono" />
            </label>
            <label className="text-xs flex-1 min-w-[120px]">
              Title
              <input type="text" value={title} onChange={e => setTitle(e.target.value)} className="block border rounded px-2 py-1 w-full" placeholder="optional" />
            </label>
          </div>

          <div className="text-xs font-bold text-gray-600 mt-2">Steps</div>
          {newSteps.map((step, i) => (
            <div key={i} className="flex items-center gap-2 pl-4 border-l-2 border-blue-300">
              <span className="text-xs text-gray-400 w-4">{i + 1}.</span>
              <select
                value={step.assigned_to}
                onChange={e => updateStep(i, 'assigned_to', e.target.value)}
                required
                className="border rounded px-2 py-1 text-xs"
              >
                {users.map(u => (
                  <option key={u.id} value={u.id}>{u.display_name}</option>
                ))}
              </select>
              <input
                type="text"
                value={step.description}
                onChange={e => updateStep(i, 'description', e.target.value)}
                placeholder="What this person needs to do"
                className="border rounded px-2 py-1 text-xs flex-1"
              />
              {newSteps.length > 1 && (
                <button type="button" onClick={() => removeStep(i)} className="text-red-500 text-xs">x</button>
              )}
            </div>
          ))}
          <div className="flex gap-2 pl-4">
            <button type="button" onClick={addStep} className="text-xs text-blue-600 hover:underline">+ Add step</button>
          </div>
          <button type="submit" disabled={busy} className="px-3 py-1 bg-green-600 text-white rounded text-xs disabled:opacity-50">
            {busy ? 'Creating...' : 'Create Job'}
          </button>
        </form>
      )}

      {/* ── Job list ── */}
      {jobs.length === 0 && !showCreate && (
        <p className="text-xs text-gray-400">No threaded jobs yet.</p>
      )}
      <div className="space-y-2">
        {jobs.map(job => (
          <div key={job.id} className="border rounded p-3 bg-gray-50">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold">{job.m_number}</span>
                {job.title && <span className="text-xs text-gray-700">{job.title}</span>}
                <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                  job.status === 'completed' ? 'bg-green-100 text-green-800'
                  : job.status === 'in_progress' ? 'bg-blue-100 text-blue-800'
                  : 'bg-yellow-100 text-yellow-800'
                }`}>
                  {job.status.replace('_', ' ')}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setExpanded(expanded === job.id ? null : job.id)} className="text-xs text-blue-600 hover:underline">
                  {expanded === job.id ? 'collapse' : 'expand'}
                </button>
                <button onClick={() => removeJob(job.id)} className="text-red-500 text-xs" title="Remove">x</button>
              </div>
            </div>

            {/* Thread chain summary: ivan -> ben -> toby */}
            <div className="mt-1 text-xs text-gray-500">
              {job.steps.map((s, i) => (
                <span key={s.id}>
                  {i > 0 && <span className="mx-1 text-gray-300">→</span>}
                  <span className={
                    s.status === 'completed' ? 'line-through text-gray-400'
                    : s.status === 'active' ? 'font-bold text-blue-700'
                    : 'text-gray-500'
                  }>
                    {s.assigned_to_name}
                  </span>
                </span>
              ))}
            </div>

            {/* Expanded thread view */}
            {expanded === job.id && (
              <div className="mt-2 ml-2 border-l-2 border-gray-200 pl-3 space-y-1">
                {job.steps.map(s => (
                  <div key={s.id} className={`flex items-start gap-2 py-1 ${
                    s.status === 'active' ? 'bg-blue-50 -ml-3 pl-3 rounded' : ''
                  }`}>
                    <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 ${
                      s.status === 'completed' ? 'bg-green-200 text-green-800'
                      : s.status === 'active' ? 'bg-blue-500 text-white'
                      : 'bg-gray-200 text-gray-500'
                    }`}>
                      {s.status === 'completed' ? '✓' : s.step_number}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-bold ${s.status === 'active' ? 'text-blue-700' : 'text-gray-700'}`}>
                          {s.assigned_to_name}
                        </span>
                        <span className={`text-[10px] px-1 py-0.5 rounded ${
                          s.status === 'completed' ? 'bg-green-100 text-green-700'
                          : s.status === 'active' ? 'bg-blue-100 text-blue-700'
                          : 'bg-gray-100 text-gray-500'
                        }`}>
                          {s.status}
                        </span>
                        {s.status === 'active' && (
                          <button
                            onClick={() => completeStep(job.id, s.step_number)}
                            className="px-1.5 py-0.5 bg-green-600 text-white rounded text-[10px] hover:bg-green-700"
                          >
                            Complete
                          </button>
                        )}
                      </div>
                      {s.description && <p className="text-xs text-gray-600">{s.description}</p>}
                      {s.completed_by_name && (
                        <p className="text-[10px] text-gray-400">
                          Completed by {s.completed_by_name}
                          {s.completed_at && ` at ${new Date(s.completed_at).toLocaleString('en-GB', { hour12: false })}`}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <p className="text-[10px] text-gray-400 mt-1">
              by {job.created_by_name} · {new Date(job.created_at).toLocaleDateString('en-GB')}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
