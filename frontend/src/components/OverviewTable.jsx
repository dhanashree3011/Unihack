

const OVERVIEW_COLS = [
  { key: 'mfg_part_num',       label: 'Part #' },
  { key: 'part_desc',          label: 'Description' },
  { key: 'manufacturer_name',  label: 'Manufacturer' },
  { key: 'brand_name',         label: 'Brand' },
  { key: 'classpath',          label: 'Classpath' },
  { key: 'product_name',       label: 'Product Name' },
  { key: 'invoice_desc',       label: 'Invoice Desc' },
]

function cellVal(d, key) {
  const v = d[key]
  if (!v) return '—'
  if (typeof v === 'object' && 'value' in v) return v.value || '—'
  return v || '—'
}

export function OverviewTable({ results, onSelect }) {
  if (!results || results.length === 0) return null

  return (
    <div className="overview-table-wrap">
      <div className="section-label">Batch Overview</div>
      <div style={{ overflowX: 'auto' }}>
        <table className="overview-table">
          <thead>
            <tr>
              {OVERVIEW_COLS.map(c => (
                <th key={c.key}>{c.label}</th>
              ))}
              <th>Fields Found</th>
              <th>Needs Review</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => {
              const d = r.data
              const fieldsFound = Object.values(d).filter(v =>
                v && typeof v === 'object' && 'value' in v && v.value
              ).length
              const needsReview = r.needs_review ? (d.fields_needing_review?.length || 1) : 0
              return (
                <tr
                  key={r.id}
                  className={`overview-row ${r.needs_review ? 'row-review' : ''}`}
                  onClick={() => onSelect && onSelect(r.id)}
                  title="Click to scroll to product card"
                >
                  {OVERVIEW_COLS.map(c => (
                    <td key={c.key} title={cellVal(d, c.key)}>
                      {cellVal(d, c.key)}
                    </td>
                  ))}
                  <td>{fieldsFound}</td>
                  <td className={needsReview > 0 ? 'cell-review' : ''}>{needsReview}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
