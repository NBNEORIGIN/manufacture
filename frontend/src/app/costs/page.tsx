'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/lib/api'

// ---------- types ----------

interface BlankCost {
  id: number
  normalized_name: string
  display_name: string
  material_cost_gbp: string
  labour_minutes: string
  is_composite: boolean
  sample_raw_blank: string
  product_count: number
  notes: string
}

interface Override {
  id: number
  product: number
  m_number: string
  description: string
  blank_raw: string
  cost_price_gbp: string | null
  notes: string
}

interface Config {
  labour_rate_gbp_per_hour: string
  overhead_per_unit_gbp: string
  default_material_gbp: string
  vat_rate_uk: string
  updated_at: string
}

type Tab = 'blanks' | 'overrides' | 'config' | 'csv'

// ---------- helpers ----------

const money = (v: string | number | null) => {
  if (v === null || v === undefined || v === '') return '—'
  const n = typeof v === 'string' ? parseFloat(v) : v
  return Number.isFinite(n) ? `£${n.toFixed(2)}` : '—'
}

function computeUnitCost(material: string, labourMin: string, cfg: Config | null): number | null {
  if (!cfg) return null
  const m = parseFloat(material)
  const l = parseFloat(labourMin)
  const rate = parseFloat(cfg.labour_rate_gbp_per_hour)
  const oh = parseFloat(cfg.overhead_per_unit_gbp)
  if (![m, l, rate, oh].every(Number.isFinite)) return null
  return m + (l / 60) * rate + oh
}

// ---------- page ----------

export default function CostConfigPage() {
  const [tab, setTab] = useState<Tab>('blanks')
  const [cfg, setCfg] = useState<Config | null>(null)

  const loadConfig = useCallback(() => {
    api('/api/costs/config/').then(r => r.json()).then(d => setCfg(d)).catch(() => {})
  }, [])

  useEffect(() => { loadConfig() }, [loadConfig])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Cost Config</h2>
        <p className="text-sm text-gray-500">
          Per-blank material cost + labour. Consumed by Cairn margin engine.
        </p>
      </div>

      <div className="mb-6 border-b border-gray-200 flex gap-1">
        {([
          ['blanks', 'Blanks'],
          ['overrides', 'M-Number Overrides'],
          ['config', 'Labour / Overhead / VAT'],
          ['csv', 'CSV Upload'],
        ] as [Tab, string][]).map(([t, label]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px ' +
              (tab === t
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-gray-500 hover:text-gray-800')
            }
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'blanks'    && <BlanksTab cfg={cfg} />}
      {tab === 'overrides' && <OverridesTab />}
      {tab === 'config'    && <ConfigTab cfg={cfg} onSaved={loadConfig} />}
      {tab === 'csv'       && <CsvTab />}
    </div>
  )
}

// ---------- blanks tab ----------

function BlanksTab({ cfg }: { cfg: Config | null }) {
  const [rows, setRows] = useState<BlankCost[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [saving, setSaving] = useState<number | null>(null)
  const [resyncMsg, setResyncMsg] = useState<string>('')

  const load = useCallback(() => {
    setLoading(true)
    const q = new URLSearchParams()
    if (search.trim()) q.set('search', search.trim())
    api(`/api/costs/blanks/?${q}`).then(r => r.json()).then(d => {
      setRows(Array.isArray(d) ? d : (d.results || []))
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [search])

  useEffect(() => { load() }, [load])

  const resync = async () => {
    setResyncMsg('Scanning…')
    const res = await api('/api/costs/blanks/resync/', { method: 'POST' }).then(r => r.json())
    setResyncMsg(`${res.blanks_created} new, ${res.product_counts_updated} counts updated, ${res.total_blanks} total.`)
    load()
  }

  const saveRow = async (row: BlankCost, patch: Partial<BlankCost>) => {
    setSaving(row.id)
    const res = await api(`/api/costs/blanks/${row.id}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) {
      const updated = await res.json()
      setRows(prev => prev.map(r => r.id === row.id ? { ...r, ...updated } : r))
    }
    setSaving(null)
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          className="px-3 py-1.5 border rounded text-sm flex-1"
          placeholder="Search blank name…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <button
          onClick={resync}
          className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded"
          title="Rescan Product.blank strings for new or removed values"
        >
          Resync
        </button>
        {resyncMsg && <span className="text-xs text-gray-500">{resyncMsg}</span>}
      </div>

      {loading ? <p className="text-gray-400">Loading…</p> : (
        <div className="bg-white rounded shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="text-left px-3 py-2">Blank</th>
                <th className="text-right px-3 py-2">Products</th>
                <th className="text-right px-3 py-2 w-32">Material £</th>
                <th className="text-right px-3 py-2 w-32">Labour min</th>
                <th className="text-right px-3 py-2">Unit cost</th>
                <th className="text-left px-3 py-2">Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <BlankRow
                  key={r.id}
                  row={r}
                  cfg={cfg}
                  saving={saving === r.id}
                  onSave={(patch) => saveRow(r, patch)}
                />
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={6} className="p-6 text-center text-gray-400">No blanks found. Click Resync.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function BlankRow({
  row, cfg, saving, onSave,
}: {
  row: BlankCost
  cfg: Config | null
  saving: boolean
  onSave: (patch: Partial<BlankCost>) => void
}) {
  const [material, setMaterial] = useState(row.material_cost_gbp)
  const [labour, setLabour] = useState(row.labour_minutes)
  const [notes, setNotes] = useState(row.notes)

  useEffect(() => { setMaterial(row.material_cost_gbp); setLabour(row.labour_minutes); setNotes(row.notes) }, [row.id])

  const dirty =
    material !== row.material_cost_gbp ||
    labour !== row.labour_minutes ||
    notes !== row.notes

  const unit = computeUnitCost(material, labour, cfg)

  return (
    <tr className="border-t border-gray-100">
      <td className="px-3 py-2">
        <div className="font-medium">{row.display_name || row.normalized_name}</div>
        {row.is_composite && (
          <div className="text-xs text-amber-700">
            Composite — prefer M-number override
          </div>
        )}
      </td>
      <td className="px-3 py-2 text-right text-gray-500">{row.product_count}</td>
      <td className="px-3 py-2 text-right">
        <input
          type="number" step="0.01" min="0"
          value={material}
          onChange={e => setMaterial(e.target.value)}
          className="w-24 px-2 py-1 border rounded text-right"
        />
      </td>
      <td className="px-3 py-2 text-right">
        <input
          type="number" step="0.1" min="0"
          value={labour}
          onChange={e => setLabour(e.target.value)}
          className="w-24 px-2 py-1 border rounded text-right"
        />
      </td>
      <td className="px-3 py-2 text-right font-medium">{unit !== null ? `£${unit.toFixed(2)}` : '—'}</td>
      <td className="px-3 py-2">
        <div className="flex gap-2">
          <input
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="notes…"
            className="flex-1 px-2 py-1 border rounded text-xs"
          />
          <button
            disabled={!dirty || saving}
            onClick={() => onSave({ material_cost_gbp: material, labour_minutes: labour, notes })}
            className="px-3 py-1 text-xs bg-blue-600 text-white rounded disabled:bg-gray-300"
          >
            {saving ? '…' : 'Save'}
          </button>
        </div>
      </td>
    </tr>
  )
}

// ---------- overrides tab ----------

function OverridesTab() {
  const [rows, setRows] = useState<Override[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [addMNumber, setAddMNumber] = useState('')
  const [addErr, setAddErr] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    const q = new URLSearchParams()
    if (search.trim()) q.set('search', search.trim())
    api(`/api/costs/overrides/?${q}`).then(r => r.json()).then(d => {
      setRows(Array.isArray(d) ? d : (d.results || []))
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [search])

  useEffect(() => { load() }, [load])

  const addOverride = async () => {
    setAddErr('')
    const m = addMNumber.trim().toUpperCase()
    if (!m) return
    const res = await api('/api/costs/overrides/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ m_number: m }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      setAddErr(err.error || err.detail || 'Failed to create override')
      return
    }
    setAddMNumber('')
    load()
  }

  const saveRow = async (row: Override, patch: Partial<Override>) => {
    const res = await api(`/api/costs/overrides/${row.id}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) {
      const updated = await res.json()
      setRows(prev => prev.map(r => r.id === row.id ? { ...r, ...updated } : r))
    }
  }

  const deleteRow = async (row: Override) => {
    if (!confirm(`Remove override for ${row.m_number}?`)) return
    const res = await api(`/api/costs/overrides/${row.id}/`, { method: 'DELETE' })
    if (res.ok) setRows(prev => prev.filter(r => r.id !== row.id))
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          className="px-3 py-1.5 border rounded text-sm flex-1"
          placeholder="Search M-number or description…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <input
          className="px-3 py-1.5 border rounded text-sm w-32"
          placeholder="M0123"
          value={addMNumber}
          onChange={e => setAddMNumber(e.target.value)}
        />
        <button
          onClick={addOverride}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded"
        >
          Add override
        </button>
      </div>
      {addErr && <div className="mb-3 text-sm text-red-600">{addErr}</div>}

      {loading ? <p className="text-gray-400">Loading…</p> : (
        <div className="bg-white rounded shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="text-left px-3 py-2 w-24">M-number</th>
                <th className="text-left px-3 py-2">Description</th>
                <th className="text-left px-3 py-2">Blank</th>
                <th className="text-right px-3 py-2 w-32">Cost £</th>
                <th className="text-left px-3 py-2">Notes</th>
                <th className="px-3 py-2 w-16"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <OverrideRow key={r.id} row={r} onSave={(p) => saveRow(r, p)} onDelete={() => deleteRow(r)} />
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={6} className="p-6 text-center text-gray-400">
                  No overrides. Add one by M-number above for composite blanks or manual cost figures.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function OverrideRow({ row, onSave, onDelete }: {
  row: Override
  onSave: (patch: Partial<Override>) => void
  onDelete: () => void
}) {
  const [cost, setCost] = useState(row.cost_price_gbp ?? '')
  const [notes, setNotes] = useState(row.notes)
  useEffect(() => { setCost(row.cost_price_gbp ?? ''); setNotes(row.notes) }, [row.id])
  const dirty = (cost || '') !== (row.cost_price_gbp ?? '') || notes !== row.notes

  return (
    <tr className="border-t border-gray-100">
      <td className="px-3 py-2 font-mono text-xs">{row.m_number}</td>
      <td className="px-3 py-2">{row.description}</td>
      <td className="px-3 py-2 text-gray-500">{row.blank_raw}</td>
      <td className="px-3 py-2 text-right">
        <input
          type="number" step="0.01" min="0"
          value={cost}
          onChange={e => setCost(e.target.value)}
          placeholder="unset"
          className="w-24 px-2 py-1 border rounded text-right"
        />
      </td>
      <td className="px-3 py-2">
        <div className="flex gap-2">
          <input
            value={notes}
            onChange={e => setNotes(e.target.value)}
            className="flex-1 px-2 py-1 border rounded text-xs"
          />
          <button
            disabled={!dirty}
            onClick={() => onSave({ cost_price_gbp: cost === '' ? null : cost, notes })}
            className="px-3 py-1 text-xs bg-blue-600 text-white rounded disabled:bg-gray-300"
          >
            Save
          </button>
        </div>
      </td>
      <td className="px-3 py-2 text-right">
        <button onClick={onDelete} className="text-gray-400 hover:text-red-600 text-xs">✕</button>
      </td>
    </tr>
  )
}

// ---------- config tab ----------

function ConfigTab({ cfg, onSaved }: { cfg: Config | null, onSaved: () => void }) {
  const [labour, setLabour] = useState('')
  const [overhead, setOverhead] = useState('')
  const [defaultMat, setDefaultMat] = useState('')
  const [vat, setVat] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!cfg) return
    setLabour(cfg.labour_rate_gbp_per_hour)
    setOverhead(cfg.overhead_per_unit_gbp)
    setDefaultMat(cfg.default_material_gbp)
    setVat(cfg.vat_rate_uk)
  }, [cfg])

  const save = async () => {
    setMsg('')
    const res = await api('/api/costs/config/', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        labour_rate_gbp_per_hour: labour,
        overhead_per_unit_gbp: overhead,
        default_material_gbp: defaultMat,
        vat_rate_uk: vat,
      }),
    })
    if (res.ok) { setMsg('Saved.'); onSaved() }
    else setMsg('Save failed.')
  }

  if (!cfg) return <p className="text-gray-400">Loading…</p>

  return (
    <div className="bg-white rounded shadow p-6 max-w-2xl">
      <div className="grid grid-cols-2 gap-4">
        <Field label="Labour rate (£/hour)" value={labour} onChange={setLabour} step="0.01" />
        <Field label="Overhead per unit (£)" value={overhead} onChange={setOverhead} step="0.01" />
        <Field label="Default material cost (£)" value={defaultMat} onChange={setDefaultMat} step="0.01"
               hint="Used when a product's blank has no BlankCost row (low confidence)." />
        <Field label="UK VAT rate (fraction, e.g. 0.2)" value={vat} onChange={setVat} step="0.001"
               hint="Applied by Cairn margin engine for UK input-VAT reclaim." />
      </div>
      <div className="mt-6 flex items-center gap-3">
        <button onClick={save} className="px-4 py-2 bg-blue-600 text-white rounded text-sm">Save</button>
        {msg && <span className="text-sm text-gray-500">{msg}</span>}
      </div>
      <p className="mt-4 text-xs text-gray-500">
        Last updated {cfg.updated_at ? new Date(cfg.updated_at).toLocaleString() : '—'}
      </p>
    </div>
  )
}

function Field({ label, value, onChange, step, hint }: {
  label: string; value: string; onChange: (v: string) => void; step?: string; hint?: string
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-gray-600 uppercase">{label}</span>
      <input
        type="number" step={step} min="0"
        value={value}
        onChange={e => onChange(e.target.value)}
        className="mt-1 w-full px-3 py-2 border rounded"
      />
      {hint && <span className="mt-1 block text-xs text-gray-400">{hint}</span>}
    </label>
  )
}

// ---------- csv tab ----------

function CsvTab() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<any>(null)
  const [uploading, setUploading] = useState(false)

  const upload = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setUploading(true); setResult(null)
    const fd = new FormData()
    fd.append('file', file)
    const res = await api('/api/costs/blanks/upload-csv/', { method: 'POST', body: fd })
    const json = await res.json().catch(() => ({ error: 'non-json response' }))
    setResult(json)
    setUploading(false)
  }

  return (
    <div className="bg-white rounded shadow p-6 max-w-3xl">
      <h3 className="font-medium mb-2">Batch update blank costs from CSV</h3>
      <p className="text-sm text-gray-600 mb-4">
        Column headers (case-insensitive): one of <code>normalized_name</code>, <code>display_name</code>,
        or <code>sample_raw_blank</code> to identify the row, then any of{' '}
        <code>material_cost_gbp</code>, <code>labour_minutes</code>, <code>notes</code>.
        Rows that don't match existing BlankCost entries are reported as <code>not_found</code> — run Resync first if
        you've added new products.
      </p>
      <div className="flex items-center gap-3">
        <input type="file" accept=".csv,text/csv" ref={fileRef} />
        <button onClick={upload} disabled={uploading}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:bg-gray-300">
          {uploading ? 'Uploading…' : 'Upload'}
        </button>
      </div>
      {result && (
        <div className="mt-4 text-sm">
          <div className="font-medium">
            {result.total_updated ?? 0} rows updated
            {result.not_found?.length ? `, ${result.not_found.length} not found` : ''}
            {result.errors?.length ? `, ${result.errors.length} errors` : ''}.
          </div>
          <pre className="mt-2 p-3 bg-gray-50 rounded text-xs overflow-auto max-h-80">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
