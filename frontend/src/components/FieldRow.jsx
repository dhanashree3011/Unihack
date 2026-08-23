import { useState } from 'react'

function confTier(conf) {
  if (conf >= 0.8) return 'high'
  if (conf >= 0.55) return 'mid'
  if (conf > 0) return 'low'
  return 'unknown'
}

export function ConfDot({ conf }) {
  return <span className={`dot dot-${confTier(conf)}`} />
}

export function FieldRow({ label, field, jobId, resultId, fieldPath, onEdited }) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(field?.value || '')

  if (!field) return null
  const hasValue = field.value !== null && field.value !== undefined && field.value !== ''
  const tier = confTier(field.confidence)

  async function save() {
    await onEdited(resultId, `${fieldPath}.value`, draft)
    setEditing(false)
  }

  return (
    <div className="field-row">
      <div className="field-name">{label}</div>
      <div className="field-value-wrap">
        {editing ? (
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              className="editable-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              autoFocus
            />
            <button className="btn btn-primary" style={{ width: 'auto', padding: '4px 10px' }} onClick={save}>
              ✓
            </button>
          </div>
        ) : (
          <div className={`field-value ${hasValue ? '' : 'empty'}`}>
            {hasValue ? field.value : 'unknown — not found in evidence'}
            {field.uom ? ` ${field.uom}` : ''}
          </div>
        )}

        {field.conflicting_values?.length > 0 && (
          <div className="conflict-note">⚠ conflicting: {field.conflicting_values.join(', ')}</div>
        )}

        {expanded && field.evidence?.length > 0 && (
          <div>
            <div className="evidence-trail">
              {field.evidence.map((ev, i) => (
                <div className="evidence-chip" key={i} title={ev.method}>
                  <ConfDot conf={field.confidence} />
                  <a href={ev.source_url} target="_blank" rel="noreferrer">
                    {ev.domain || ev.source_url}
                  </a>
                </div>
              ))}
            </div>
            {field.evidence[0]?.supporting_text && (
              <div className="evidence-snippet">"{field.evidence[0].supporting_text}"</div>
            )}
          </div>
        )}
        {expanded && (!field.evidence || field.evidence.length === 0) && (
          <div className="evidence-snippet">No source evidence recorded for this field.</div>
        )}
      </div>
      <div className="field-conf" onClick={() => setExpanded((e) => !e)}>
        <ConfDot conf={field.confidence} />
        {hasValue ? `${Math.round(field.confidence * 100)}%` : '—'}
        {jobId && hasValue && (
          <span
            style={{ marginLeft: 6, color: 'var(--ink-faint)', cursor: 'pointer' }}
            onClick={(e) => {
              e.stopPropagation()
              setDraft(field.value)
              setEditing(true)
            }}
            title="Edit (human review)"
          >
            ✎
          </span>
        )}
      </div>
    </div>
  )
}
