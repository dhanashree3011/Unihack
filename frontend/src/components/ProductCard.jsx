import { useState, useEffect } from 'react'
import { FieldRow, ConfDot } from './FieldRow.jsx'

export function ProductCard({ result, jobId, onEdited, getFieldsPopulatedCount, forceOpen, initialTab }) {
  const [open, setOpen] = useState(forceOpen || false)
  const [activeTab, setActiveTab] = useState(initialTab || (result.needs_review ? 'review' : 'identity'))
  const [showAllAttrs, setShowAllAttrs] = useState(false)

  useEffect(() => {
    if (forceOpen !== undefined) {
      setOpen(forceOpen)
    }
  }, [forceOpen])

  useEffect(() => {
    if (initialTab) {
      setActiveTab(initialTab)
    }
  }, [initialTab])

  const d = result.data
  const conf = result.overall_confidence
  const tier = conf >= 0.8 ? 'high' : conf >= 0.55 ? 'mid' : 'low'
  const isFailed = d.processing_log?.some(l => l.includes('FATAL'))
  const status = isFailed ? 'Failed' : 'Completed'

  const attrs = d.attributes || []
  const populatedCount = getFieldsPopulatedCount(d)
  const sourcesCount = d.sources_scraped?.length || 0
  const processingTime = d.timings?.total ? `${d.timings.total}s` : '—'
  const visibleAttrs = showAllAttrs ? attrs : attrs.slice(0, 6)

  return (
    <div className="product-card">
      <div className={`product-head ${open ? 'open' : ''}`} onClick={() => setOpen((o) => !o)}>
        <div className="product-head-grid">
          <div className="head-col title-col">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ConfDot conf={conf} />
              <div className="product-title" title={d.part_desc}>{d.part_desc}</div>
            </div>
            <div className="product-part">{d.mfg_part_num}</div>
          </div>
          
          <div className="head-col">
            <span className="col-label">Category / Name</span>
            <div className="col-val">{d.product_category?.value || '—'}</div>
            <div className="col-sub">{d.product_name?.value || '—'}</div>
          </div>

          <div className="head-col">
            <span className="col-label">Manufacturer / Brand</span>
            <div className="col-val">{d.manufacturer_name?.value || d.part_manuf || '—'}</div>
            <div className="col-sub">{d.brand_name?.value || '—'}</div>
          </div>

          <div className="head-col stat-col">
            <span className="col-label">Extracted / Fields / Sources</span>
            <div className="col-val">{attrs.length} attrs / {populatedCount} fields</div>
            <div className="col-sub">{sourcesCount} sources</div>
          </div>

          <div className="head-col stat-col">
            <span className="col-label">Time / Status</span>
            <div className="col-val">{processingTime}</div>
            <div className={`col-sub status-${status.toLowerCase()}`}>{status}</div>
          </div>

          <div className="head-col badge-col" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
            {result.needs_review ? <span className="review-badge">REVIEW REQ</span> : <span className="approved-badge">APPROVED</span>}
            <span className={`tag tag-${tier}`}>{Math.round(conf * 100)}% conf</span>
          </div>
        </div>
      </div>

      {open && (
        <div className="product-body">
          <div className="tabs-header">
            {result.needs_review && (
              <button
                className={`tab-link ${activeTab === 'review' ? 'active' : ''}`}
                style={{ color: 'var(--amber)', fontWeight: 600 }}
                onClick={() => setActiveTab('review')}
              >
                ⚠️ Review ({d.fields_needing_review?.length || 1})
              </button>
            )}
            <button className={`tab-link ${activeTab === 'identity' ? 'active' : ''}`} onClick={() => setActiveTab('identity')}>Identity</button>
            <button className={`tab-link ${activeTab === 'classification' ? 'active' : ''}`} onClick={() => setActiveTab('classification')}>Classification</button>
            <button className={`tab-link ${activeTab === 'attributes' ? 'active' : ''}`} onClick={() => setActiveTab('attributes')}>Key Attributes ({attrs.length})</button>
            <button className={`tab-link ${activeTab === 'descriptions' ? 'active' : ''}`} onClick={() => setActiveTab('descriptions')}>Descriptions</button>
            <button className={`tab-link ${activeTab === 'evidence' ? 'active' : ''}`} onClick={() => setActiveTab('evidence')}>Sources & Evidence</button>
            <button className={`tab-link ${activeTab === 'validation' ? 'active' : ''}`} onClick={() => setActiveTab('validation')}>Validation & Timings</button>
          </div>

          <div className="tab-content" style={{ marginTop: 16 }}>
            {activeTab === 'review' && (
              <div>
                <div className="banner banner-warning" style={{ marginBottom: 12 }}>
                  <span>
                    Low confidence or missing evidence detected on this product. Approve or edit the values below to verify and cache the corrections.
                  </span>
                </div>
                <div className="field-table">
                  {(d.fields_needing_review || ['manufacturer_name', 'brand_name', 'product_category', 'classpath']).map((fname) => {
                    const fieldObj = d[fname] || { value: '', confidence: 0 }
                    const label = fname.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
                    return (
                      <FieldRow
                        key={fname}
                        label={label}
                        field={fieldObj}
                        jobId={jobId}
                        resultId={result.id}
                        fieldPath={fname}
                        onEdited={onEdited}
                      />
                    )
                  })}
                </div>
              </div>
            )}

            {activeTab === 'identity' && (
              <div className="field-table">
                <FieldRow label="Manufacturer" field={d.manufacturer_name} jobId={jobId} resultId={result.id} fieldPath="manufacturer_name" onEdited={onEdited} />
                <FieldRow label="Brand" field={d.brand_name} jobId={jobId} resultId={result.id} fieldPath="brand_name" onEdited={onEdited} />
                <FieldRow label="Trade Name" field={d.trade_name} jobId={jobId} resultId={result.id} fieldPath="trade_name" onEdited={onEdited} />
                <FieldRow label="Product Name" field={d.product_name} jobId={jobId} resultId={result.id} fieldPath="product_name" onEdited={onEdited} />
                <FieldRow label="UPC" field={d.upc} jobId={jobId} resultId={result.id} fieldPath="upc" onEdited={onEdited} />
                <FieldRow label="Country of Origin" field={d.country_of_origin} jobId={jobId} resultId={result.id} fieldPath="country_of_origin" onEdited={onEdited} />
                <FieldRow label="Warranty" field={d.warranty} jobId={jobId} resultId={result.id} fieldPath="warranty" onEdited={onEdited} />
              </div>
            )}

            {activeTab === 'classification' && (
              <div className="field-table">
                <FieldRow label="Category" field={d.product_category} jobId={jobId} resultId={result.id} fieldPath="product_category" onEdited={onEdited} />
                <FieldRow label="Classpath" field={d.classpath} jobId={jobId} resultId={result.id} fieldPath="classpath" onEdited={onEdited} />
                <div className="field-row">
                  <div className="field-name">Dept</div>
                  <div className="field-value-wrap"><div className="field-value">{d.dept || '—'}</div></div>
                  <div className="field-conf">—</div>
                </div>
                <div className="field-row">
                  <div className="field-name">Class</div>
                  <div className="field-value-wrap"><div className="field-value">{d.product_class || '—'}</div></div>
                  <div className="field-conf">—</div>
                </div>
                <div className="field-row">
                  <div className="field-name">Fine Class</div>
                  <div className="field-value-wrap"><div className="field-value">{d.fine_class || '—'}</div></div>
                  <div className="field-conf">—</div>
                </div>
              </div>
            )}

            {activeTab === 'attributes' && (
              <div>
                <div className="field-table">
                  <FieldRow label="Length" field={d.length} jobId={jobId} resultId={result.id} fieldPath="length" onEdited={onEdited} />
                  <FieldRow label="Width" field={d.width} jobId={jobId} resultId={result.id} fieldPath="width" onEdited={onEdited} />
                  <FieldRow label="Height" field={d.height} jobId={jobId} resultId={result.id} fieldPath="height" onEdited={onEdited} />
                  <FieldRow label="Weight" field={d.weight} jobId={jobId} resultId={result.id} fieldPath="weight" onEdited={onEdited} />
                </div>
                
                {attrs.length > 0 && (
                  <div style={{ marginTop: 20 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                      <div className="section-label" style={{ margin: 0 }}>Dynamic Attributes</div>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--ink-dim)', cursor: 'pointer' }}>
                        <input type="checkbox" checked={showAllAttrs} onChange={(e) => setShowAllAttrs(e.target.checked)} />
                        Show all extracted attributes
                      </label>
                    </div>

                    <div className="field-table">
                      {visibleAttrs.map((a, i) => (
                        <FieldRow
                          key={i}
                          label={`${a.label.value} (${a.uom?.value || 'no UOM'})`}
                          field={a.value}
                          jobId={jobId}
                          resultId={result.id}
                          fieldPath={`attributes.${i}.value`}
                          onEdited={onEdited}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'descriptions' && (
              <div className="field-table">
                <FieldRow label="Mobile Description" field={d.mobile_desc} jobId={jobId} resultId={result.id} fieldPath="mobile_desc" onEdited={onEdited} />
                <FieldRow label="Invoice Description" field={d.invoice_desc} jobId={jobId} resultId={result.id} fieldPath="invoice_desc" onEdited={onEdited} />
                <FieldRow label="Short Description" field={d.short_desc} jobId={jobId} resultId={result.id} fieldPath="short_desc" onEdited={onEdited} />
                <FieldRow label="Long Description 1" field={d.long_desc1} jobId={jobId} resultId={result.id} fieldPath="long_desc1" onEdited={onEdited} />
                <FieldRow label="Retail Description" field={d.retail_desc} jobId={jobId} resultId={result.id} fieldPath="retail_desc" onEdited={onEdited} />
                <FieldRow label="Marketing Description" field={d.marketing_desc} jobId={jobId} resultId={result.id} fieldPath="marketing_desc" onEdited={onEdited} />
              </div>
            )}

            {activeTab === 'evidence' && (
              <div>
                <FieldRow label="MFR URL" field={d.mfr_url} jobId={jobId} resultId={result.id} fieldPath="mfr_url" onEdited={onEdited} />
                <FieldRow label="Specification Sheet" field={d.spec_sheet_url} jobId={jobId} resultId={result.id} fieldPath="spec_sheet_url" onEdited={onEdited} />
                <FieldRow label="Product Image" field={d.product_image_url} jobId={jobId} resultId={result.id} fieldPath="product_image_url" onEdited={onEdited} />

                {d.with_feature?.value && (
                  <div style={{ marginTop: 14 }}>
                    <div className="section-label">With Feature</div>
                    <div style={{ fontSize: 13, background: 'var(--panel-raised)', padding: '10px 14px', borderRadius: 4 }}>
                      {d.with_feature.value}
                    </div>
                  </div>
                )}

                {d.item_features?.length > 0 && (
                  <div style={{ marginTop: 14 }}>
                    <div className="section-label">Features list ({d.item_features.length})</div>
                    <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: 'var(--ink-dim)', lineHeight: 1.6 }}>
                      {d.item_features.map((feat, idx) => (
                        <li key={idx}>{feat.value}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="section-label" style={{ marginTop: 20 }}>Sources Scraped ({sourcesCount})</div>
                <div className="evidence-trail">
                  {(d.sources_scraped || []).map((url, i) => (
                    <div className="evidence-chip" key={i}>
                      <a href={url} target="_blank" rel="noreferrer">
                        {(() => {
                          try { return new URL(url).hostname } catch { return url }
                        })()}
                      </a>
                    </div>
                  ))}
                </div>

                {d.processing_log?.length > 0 && (
                  <div style={{ marginTop: 20 }}>
                    <div className="section-label">Processing Log</div>
                    <div style={{ maxHeight: 200, overflowY: 'auto', background: 'var(--bg)', padding: 10, borderRadius: 4 }}>
                      {d.processing_log.map((l, i) => (
                        <div className="log-line" key={i}>› {l}</div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'validation' && (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                  <div>
                    <div className="section-label">Confidence Metrics</div>
                    <div style={{ background: 'var(--panel-raised)', padding: 14, borderRadius: 6 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 13 }}>
                        <span>Overall Confidence Score</span>
                        <span style={{ fontWeight: 600, color: 'var(--teal)' }}>{Math.round(conf * 100)}%</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                        <span>Status</span>
                        <span className={`status-${status.toLowerCase()}`}>{status}</span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="section-label">Fields Requiring Review</div>
                    <div style={{ background: 'var(--panel-raised)', padding: 14, borderRadius: 6, maxHeight: 150, overflowY: 'auto' }}>
                      {result.needs_review && d.fields_needing_review?.length > 0 ? (
                        <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: 'var(--red)' }}>
                          {d.fields_needing_review.map((f, i) => <li key={i}>{f}</li>)}
                        </ul>
                      ) : (
                        <span style={{ fontSize: 13, color: 'var(--teal)' }}>✓ All fields verified & accepted</span>
                      )}
                    </div>
                  </div>
                </div>

                {d.timings && Object.keys(d.timings).length > 0 && (
                  <div style={{ marginTop: 20 }}>
                    <div className="section-label">Processing Timings</div>
                    <div className="timings-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
                      {Object.entries(d.timings).map(([stage, dur]) => (
                        <div key={stage} style={{ background: 'var(--panel-raised)', padding: '10px 14px', borderRadius: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontSize: 12, color: 'var(--ink-faint)', textTransform: 'capitalize' }}>
                            {stage.replace('_', ' ')}
                          </span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600 }}>{dur}s</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
