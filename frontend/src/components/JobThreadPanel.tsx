'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'

/**
 * Multi-step threaded job creator + display (Ivan review #10 item 5, #11 items 2-7).
 *
 * Review #11 changes:
 * - M-number field removed; title is the anchor, bold + larger font
 * - No user pre-selected by default in dropdowns
 * - Cascading user dropdowns: up to 4 users per step
 * - Description field visible for each step
 * - Real-time polling: job list refreshes every 5s for status changes
 */

interface UserOption { id: number; display_name: string }

interface Step {
  id: number; step_number: number
  assigned_to_ids: number[]; assigned_to_names: string[]
  description: string; status: string
  completed_at: string | null; completed_by_name: string
}

interface JobItem {
  id: number; m_number: string; description: string
  created_by_name: string; title: string; notes: string
  status: string; steps: Step[]; step_chain: string; created_at: string
  customer: string; deadline: string | null; asap: boolean
}

/**
 * Deadline urgency background colour.
 * ASAP or <1 day => red. 7+ days => green. Interpolates between.
 */
function deadlineStyle(deadline: string | null, asap: boolean): React.CSSProperties {
  if (asap) return { backgroundColor: '#fecaca', color: '#991b1b', fontWeight: 700 }
  if (!deadline) return {}
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const target = new Date(deadline)
  target.setHours(0, 0, 0, 0)
  const days = Math.ceil((target.getTime() - today.getTime()) / (24 * 60 * 60 * 1000))
  // Past due or ASAP → red
  if (days <= 0) return { backgroundColor: '#fecaca', color: '#991b1b', fontWeight: 700 }
  if (days >= 7) return { backgroundColor: '#bbf7d0', color: '#166534' }
  // Interpolate green (7d) → red (1d)
  const t = (7 - days) / 6 // 0 at 7 days, 1 at 1 day
  const r = Math.round(187 + (254 - 187) * t)
  const g = Math.round(247 + (202 - 247) * t)
  const b = Math.round(208 + (202 - 208) * t)
  const textR = Math.round(22 + (153 - 22) * t)
  const textG = Math.round(101 + (27 - 101) * t)
  const textB = Math.round(52 + (27 - 52) * t)
  return {
    backgroundColor: `rgb(${r}, ${g}, ${b})`,
    color: `rgb(${textR}, ${textG}, ${textB})`,
    fontWeight: t > 0.5 ? 700 : 500,
  }
}

function formatDeadline(deadline: string | null, asap: boolean): string {
  if (asap) return 'ASAP'
  if (!deadline) return ''
  const d = new Date(deadline)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

/** Cascading user dropdown — up to 4 users, next slot appears when previous is filled. */
function StepUserCascade({
  users,
  selectedIds,
  onChange,
}: {
  users: UserOption[]
  selectedIds: string[]
  onChange: (ids: string[]) => void
}) {
  const maxSlots = 4
  const filledCount = selectedIds.filter(id => id !== '').length
  const slots = Math.min(maxSlots, filledCount + 1)

  const update = (index: number, value: string) => {
    const copy = [...selectedIds]
    copy[index] = value
    if (value === '') {
      onChange(copy.slice(0, index).filter(id => id !== ''))
    } else {
      onChange(copy.slice(0, index + 1))
    }
  }

  const effective: string[] = []
  for (let i = 0; i < slots; i++) {
    effective.push(selectedIds[i] || '')
  }

  return (
    <div className="flex gap-1 flex-wrap">
      {effective.map((val, i) => {
        const taken = new Set(effective.filter((v, j) => v && j !== i))
        const available = users.filter(u => !taken.has(String(u.id)))
        return (
          <select
            key={i}
            value={val}
            onChange={e => update(i, e.target.value)}
            required={i === 0}
            className="border rounded px-2 py-1 text-xs"
          >
            <option value="">{i === 0 ? 'Select user...' : '+ user'}</option>
            {available.map(u => (
              <option key={u.id} value={u.id}>{u.display_name}</option>
            ))}
          </select>
        )
      })}
    </div>
  )
}

export default function JobThreadPanel() {
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [users, setUsers] = useState<UserOption[]>([])
  const [expanded, setExpanded] = useState<number | null>(null)

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [title, setTitle] = useState('')
  const [notes, setNotes] = useState('')
  const [customer, setCustomer] = useState('')
  const [deadline, setDeadline] = useState('')
  const [asap, setAsap] = useState(false)
  const [showDeadlinePicker, setShowDeadlinePicker] = useState(false)
  const [newSteps, setNewSteps] = useState<Array<{ user_ids: string[]; description: string }>>([
    { user_ids: [], description: '' },
  ])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadJobs = useCallback(async () => {
    try {
      const j = await api('/api/jobs/?page_size=20').then(r => r.json())
      setJobs(j.results ?? j)
    } catch { /* silent */ }
  }, [])

  const loadUsers = useCallback(async () => {
    try {
      const u = await api('/api/auth/users/').then(r => r.json())
      setUsers(u.users ?? [])
    } catch { /* silent */ }
  }, [])

  useEffect(() => {
    loadJobs()
    loadUsers()
  }, [loadJobs, loadUsers])

  // Real-time polling: refresh job list every 5 seconds
  useEffect(() => {
    pollRef.current = setInterval(loadJobs, 5000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [loadJobs])

  const addStep = () => {
    setNewSteps([...newSteps, { user_ids: [], description: '' }])
  }

  const removeStep = (i: number) => {
    if (newSteps.length <= 1) return
    setNewSteps(newSteps.filter((_, idx) => idx !== i))
  }

  const updateStepUsers = (i: number, ids: string[]) => {
    const copy = [...newSteps]
    copy[i] = { ...copy[i], user_ids: ids }
    setNewSteps(copy)
  }

  const updateStepDesc = (i: number, val: string) => {
    const copy = [...newSteps]
    copy[i] = { ...copy[i], description: val }
    setNewSteps(copy)
  }

  const createJob = async (e: React.FormEvent) => {
    e.preventDefault()
    // Validate at least one user per step
    for (let i = 0; i < newSteps.length; i++) {
      if (newSteps[i].user_ids.filter(id => id !== '').length === 0) {
        setMsg(`Error: Step ${i + 1} needs at least one user`)
        return
      }
    }
    setBusy(true)
    setMsg('')
    try {
      const r = await api('/api/jobs/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          notes,
          customer,
          deadline: asap ? null : (deadline || null),
          asap,
          steps_input: newSteps.map(s => ({
            assigned_to_ids: s.user_ids.filter(id => id !== '').map(Number),
            description: s.description,
          })),
        }),
      })
      if (r.ok) {
        setTitle('')
        setNotes('')
        setCustomer('')
        setDeadline('')
        setAsap(false)
        setShowDeadlinePicker(false)
        setNewSteps([{ user_ids: [], description: '' }])
        setShowCreate(false)
        setMsg('Job created')
        setTimeout(() => setMsg(''), 3000)
        loadJobs()
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
    loadJobs()
  }

  const completeStep = async (jobId: number, stepNumber: number) => {
    const r = await api(`/api/jobs/${jobId}/steps/${stepNumber}/complete/`, { method: 'POST' })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      alert(d.error || `Failed: ${r.status}`)
      return
    }
    loadJobs()
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
          <label className="text-xs block">
            <span className="font-bold">Title</span>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              required
              placeholder="Job title"
              className="block border rounded px-2 py-1 w-full text-sm font-bold"
            />
          </label>

          <label className="text-xs block">
            <span className="font-bold">Customer <span className="text-gray-400 font-normal">(optional)</span></span>
            <input
              type="text"
              value={customer}
              onChange={e => setCustomer(e.target.value)}
              placeholder="Customer name, contact, etc."
              className="block border rounded px-2 py-1 w-full text-sm"
            />
          </label>

          <div className="text-xs">
            <span className="font-bold block mb-1">Deadline <span className="text-gray-400 font-normal">(optional)</span></span>
            {!showDeadlinePicker && !deadline && !asap ? (
              <button
                type="button"
                onClick={() => setShowDeadlinePicker(true)}
                className="px-3 py-1 bg-gray-200 text-gray-700 rounded text-xs hover:bg-gray-300"
              >
                Choose deadline
              </button>
            ) : (
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  type="date"
                  value={deadline}
                  onChange={e => { setDeadline(e.target.value); setAsap(false) }}
                  disabled={asap}
                  className="border rounded px-2 py-1 text-xs disabled:bg-gray-100"
                />
                <button
                  type="button"
                  onClick={() => { setAsap(!asap); if (!asap) setDeadline('') }}
                  className={`px-3 py-1 rounded text-xs font-bold ${
                    asap ? 'bg-red-500 text-white' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                  }`}
                >
                  ASAP
                </button>
                {(deadline || asap) && (
                  <span
                    className="px-2 py-1 rounded text-xs"
                    style={deadlineStyle(deadline || null, asap)}
                  >
                    {formatDeadline(deadline || null, asap)}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => { setShowDeadlinePicker(false); setDeadline(''); setAsap(false) }}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >
                  clear
                </button>
              </div>
            )}
          </div>

          <div className="text-xs font-bold text-gray-600 mt-2">Steps</div>
          {newSteps.map((step, i) => (
            <div key={i} className="flex items-start gap-2 pl-4 border-l-2 border-blue-300">
              <span className="text-xs text-gray-400 w-4 pt-1">{i + 1}.</span>
              <div className="flex-1 space-y-1">
                <div className="flex gap-2 items-start">
                  <StepUserCascade
                    users={users}
                    selectedIds={step.user_ids}
                    onChange={ids => updateStepUsers(i, ids)}
                  />
                  <input
                    type="text"
                    value={step.description}
                    onChange={e => updateStepDesc(i, e.target.value)}
                    placeholder="Step description"
                    className="border rounded px-2 py-1 text-xs flex-1"
                  />
                </div>
              </div>
              {newSteps.length > 1 && (
                <button type="button" onClick={() => removeStep(i)} className="text-red-500 text-xs pt-1">x</button>
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
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-base font-bold text-gray-900">{job.title || 'Untitled'}</span>
                {job.customer && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-100 text-gray-700" title="Customer">
                    {job.customer}
                  </span>
                )}
                {(job.deadline || job.asap) && (
                  <span
                    className="px-1.5 py-0.5 rounded text-[10px]"
                    style={deadlineStyle(job.deadline, job.asap)}
                    title="Deadline"
                  >
                    {formatDeadline(job.deadline, job.asap)}
                  </span>
                )}
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

            {/* Thread chain summary */}
            <div className="mt-1 text-xs text-gray-500">
              {job.steps.map((s, i) => (
                <span key={s.id}>
                  {i > 0 && <span className="mx-1 text-gray-300">&rarr;</span>}
                  <span className={
                    s.status === 'completed' ? 'line-through text-gray-400'
                    : s.status === 'active' ? 'font-bold text-blue-700'
                    : 'text-gray-500'
                  }>
                    {(s.assigned_to_names ?? []).join(', ')}
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
                      {s.status === 'completed' ? '\u2713' : s.step_number}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`text-xs font-bold ${s.status === 'active' ? 'text-blue-700' : 'text-gray-700'}`}>
                          {(s.assigned_to_names ?? []).join(', ')}
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
                      {s.description && <p className="text-xs text-gray-600 mt-0.5">{s.description}</p>}
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
              by {job.created_by_name} &middot; {new Date(job.created_at).toLocaleDateString('en-GB')}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
