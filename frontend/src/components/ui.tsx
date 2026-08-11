import type { ReactNode } from 'react'

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {hint && <div className="field-hint">{hint}</div>}
      {children}
    </div>
  )
}

/** Zahlenfeld, das leere Eingaben als null zurückgibt statt als NaN. */
export function NumberField({
  label,
  hint,
  value,
  onChange,
  unit,
  step = 1,
  min,
  max,
  placeholder,
}: {
  label: string
  hint?: string
  value: number | null
  onChange: (value: number | null) => void
  unit?: string
  step?: number
  min?: number
  max?: number
  placeholder?: string
}) {
  return (
    <Field label={unit ? `${label} (${unit})` : label} hint={hint}>
      <input
        type="number"
        value={value ?? ''}
        step={step}
        min={min}
        max={max}
        placeholder={placeholder}
        onChange={(e) => {
          const raw = e.target.value
          onChange(raw === '' ? null : Number(raw))
        }}
      />
    </Field>
  )
}

export function TextField({
  label,
  hint,
  value,
  onChange,
  placeholder,
  type = 'text',
  min,
  max,
}: {
  label: string
  hint?: string
  value: string | null
  onChange: (value: string | null) => void
  placeholder?: string
  type?: 'text' | 'date'
  /** Nur für `type="date"` gedacht: begrenzt den wählbaren Zeitraum. */
  min?: string
  max?: string
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        type={type}
        value={value ?? ''}
        placeholder={placeholder}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      />
    </Field>
  )
}

export function TextArea({
  label,
  hint,
  value,
  onChange,
  placeholder,
  rows = 3,
}: {
  label: string
  hint?: string
  value: string | null
  onChange: (value: string | null) => void
  placeholder?: string
  rows?: number
}) {
  return (
    <Field label={label} hint={hint}>
      <textarea
        rows={rows}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      />
    </Field>
  )
}

export function Alert({
  kind,
  children,
}: {
  kind: 'error' | 'warning' | 'success' | 'info'
  children: ReactNode
}) {
  return <div className={`alert alert-${kind}`}>{children}</div>
}

export function Stat({
  label,
  value,
  unit,
  hint,
}: {
  label: string
  value: ReactNode
  unit?: string
  hint?: ReactNode
}) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
      </div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  children,
}: {
  icon: string
  title: string
  children?: ReactNode
}) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">{icon}</div>
      <h3>{title}</h3>
      {children}
    </div>
  )
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2 className="mb-0">{title}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Schließen">
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Loading({ text = 'Lädt …' }: { text?: string }) {
  return <div className="loading">{text}</div>
}
