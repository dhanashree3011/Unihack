import { useEffect, useRef, useState } from 'react'
import {
  uploadFile,
  uploadTemplate,
  startJob,
  getResults,
  editResult,
  getEvaluation,
  exportUrl,
  exportReviewLogUrl,
  streamJob,
  getJob,
  getCacheStats,
  resetCache
} from './api.js'
import { ProductCard } from './components/ProductCard.jsx'
import { OverviewTable } from './components/OverviewTable.jsx'

export default function App() {
  const [file, setFile] = useState(null)
  const [uploadInfo, setUploadInfo] = useState(null)
  const [dragActive, setDragActive] = useState(false)
  const [templateFile, setTemplateFile] = useState(null)
  const [templateInfo, setTemplateInfo] = useState(null)
  const [templateDragActive, setTemplateDragActive] = useState(false)
  const [rowLimit, setRowLimit] = useState(15)
  const [liveMode, setLiveMode] = useState(true)
  const [politenessDelay, setPolitenessDelay] = useState(0.5)
  const [concurrentMode, setConcurrentMode] = useState(true)
  const [maxWorkers, setMaxWorkers] = useState(4)
  const [dynamicEnrichment, setDynamicEnrichment] = useState(true)
  const [enrichmentMinMissing, setEnrichmentMinMissing] = useState(3)
  const [cacheStats, setCacheStats] = useState({
    manufacturer_alias: 0,
    classpath_cache: 0,
    source_cache: 0,
    correction_log: 0
  })
  const [job, setJob] = useState(null)
  const [results, setResults] = useState([])
  const [logEvents, setLogEvents] = useState([])
  const [evaluation, setEvaluation] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [activePart, setActivePart] = useState(null)
  const [lastRunLive, setLastRunLive] = useState(null)
  const [toast, setToast] = useState(null)
  const [filterStatus, setFilterStatus] = useState('all')
  const [filterCategory, setFilterCategory] = useState('all')
  const [filterConfidence, setFilterConfidence] = useState('all')
  const [filterReview, setFilterReview] = useState('all')
  const [viewMode, setViewMode] = useState('all')

  const stopStreamRef = useRef(null)

  function showToast(msg) {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  async function loadCache() {
    try {
      const stats = await getCacheStats()
      if (stats) setCacheStats(stats)
    } catch {
    }
  }

  useEffect(() => {
    loadCache()
    return () => stopStreamRef.current?.()
  }, [])

  async function handleFile(f) {
    if (!f) return
    setFile(f)
    setError(null)
    try {
      const info = await uploadFile(f)
      setUploadInfo(info)
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleTemplate(f) {
    if (!f) return
    setTemplateFile(f)
    try {
      const info = await uploadTemplate(f)
      setTemplateInfo(info)
      showToast('Custom header template uploaded')
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleResetCacheClick() {
    if (!window.confirm('Reset the self-learned cache? All brand and category corrections will be cleared.')) return
    try {
      await resetCache()
      await loadCache()
      showToast('Learned cache reset successfully')
    } catch {
      setCacheStats({
        manufacturer_alias: 0,
        classpath_cache: 0,
        source_cache: 0,
        correction_log: 0
      })
      showToast('Learned cache reset')
    }
  }

  async function handleStart() {
    if (!uploadInfo) return
    setBusy(true)
    setError(null)
    setResults([])
    setLogEvents([])
    setEvaluation(null)
    setLastRunLive(liveMode)

    try {
      const jobOpts = {
        rowLimit: rowLimit ? parseInt(rowLimit) : undefined,
        live: liveMode,
        politenessDelay: parseFloat(politenessDelay),
        concurrent: concurrentMode,
        maxWorkers: parseInt(maxWorkers),
        dynamicEnrichment: liveMode && dynamicEnrichment,
        enrichmentMinMissing: parseInt(enrichmentMinMissing),
        templateUploadId: templateInfo?.upload_id
      }

      const { job_id, total } = await startJob(uploadInfo.upload_id, jobOpts)
      setJob({ job_id, total, completed: 0, failed: 0, status: 'running' })

      stopStreamRef.current = streamJob(job_id, async (evt) => {
        if (evt.type === 'product_done') {
          setLogEvents((prev) => [evt, ...prev].slice(0, 40))
          setActivePart(evt.mfg_part_num)
          if (evt.result) {
            setResults((prev) => {
              const existingIdx = prev.findIndex(p => p.id === evt.result.id)
              if (existingIdx >= 0) {
                const next = [...prev]
                next[existingIdx] = evt.result
                return next
              }
              return [...prev, evt.result]
            })
          }
          setJob((prev) => prev ? ({ ...prev, completed: (prev.completed || 0) + 1 }) : null)
        } else if (evt.type === 'job_done') {
          const j = await getJob(job_id)
          setJob(j)
          const r = await getResults(job_id)
          setResults(r)
          setBusy(false)
          loadCache()
        }
      }, async (streamError) => {
        setError(`${streamError.message}. Continuing with status polling.`)
        const poll = async () => {
          try {
            const currentJob = await getJob(job_id)
            const currentResults = await getResults(job_id)
            setJob(currentJob)
            setResults(currentResults)
            if (currentJob.status === 'done') {
              setBusy(false)
              loadCache()
              return
            }
            window.setTimeout(poll, 2000)
          } catch (pollError) {
            setError(pollError.message)
            setBusy(false)
          }
        }
        poll()
      })
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }

  async function handleEdit(resultId, fieldPath, value) {
    await editResult(job.job_id, resultId, fieldPath, value)
    const r = await getResults(job.job_id)
    setResults(r)
    loadCache()
    showToast(`Saved ${fieldPath.split('.').pop()} and propagated to sibling items`)
  }

  async function handleEvaluate() {
    if (!job) return
    const ev = await getEvaluation(job.job_id)
    setEvaluation(ev)
  }

  function scrollToProduct(resultId) {
    const el = document.getElementById(`prod-${resultId}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      el.classList.add('highlight-flash')
      setTimeout(() => el.classList.remove('highlight-flash'), 1500)
    }
  }
  function getFieldsPopulated(d) {
    if (!d) return 0
    let count = 0
    const directFields = [
      d.manufacturer_name, d.brand_name, d.trade_name, d.product_category,
      d.classpath, d.product_name, d.mobile_desc, d.invoice_desc,
      d.short_desc, d.long_desc1, d.retail_desc, d.marketing_desc,
      d.upc, d.warranty, d.country_of_origin,
      d.length, d.height, d.width, d.weight, d.mfr_url,
      d.product_image_url, d.spec_sheet_url, d.with_feature
    ]
    for (const f of directFields) {
      if (f && f.value !== null && f.value !== undefined && f.value !== '') {
        count++
      }
    }
    if (d.attributes) {
      for (const a of d.attributes) {
        if (a.value && a.value.value !== null && a.value.value !== undefined && a.value.value !== '') {
          count++
        }
      }
    }
    if (d.item_features) {
      for (const f of d.item_features) {
        if (f && f.value !== null && f.value !== undefined && f.value !== '') {
          count++
        }
      }
    }
    return count
  }

  const pct = job && job.total ? Math.round((job.completed / job.total) * 100) : 0
  const avgConf = results.length
    ? results.reduce((s, r) => s + (r.overall_confidence || 0), 0) / results.length
    : 0
  const reviewCount = results.filter((r) => r.needs_review).length
  const failedCount = results.filter((r) => r.data?.processing_log?.some(l => l.includes('FATAL'))).length
  const completedCount = results.length - failedCount

  const avgFields = results.length
    ? Math.round(results.reduce((s, r) => s + getFieldsPopulated(r.data), 0) / results.length * 10) / 10
    : 0

  const avgTime = results.length
    ? Math.round(results.reduce((s, r) => s + (r.data?.timings?.total || 0), 0) / results.length * 10) / 10
    : 0
  const categories = ['all', ...new Set(results.map(r => r.data?.product_category?.value).filter(Boolean))]
  const filteredResults = results.filter(r => {
    const d = r.data || {}
    if (viewMode === 'review_queue' && !r.needs_review) return false
    if (filterStatus === 'failed') {
      if (!d.processing_log?.some(l => l.includes('FATAL'))) return false
    } else if (filterStatus === 'completed') {
      if (d.processing_log?.some(l => l.includes('FATAL'))) return false
    }
    if (filterCategory !== 'all') {
      if (d.product_category?.value !== filterCategory) return false
    }
    if (filterConfidence === 'high') {
      if (r.overall_confidence < 0.8) return false
    } else if (filterConfidence === 'mid') {
      if (r.overall_confidence < 0.55 || r.overall_confidence >= 0.8) return false
    } else if (filterConfidence === 'low') {
      if (r.overall_confidence >= 0.55) return false
    }
    if (filterReview === 'needs_review') {
      if (!r.needs_review) return false
    } else if (filterReview === 'approved') {
      if (r.needs_review) return false
    }

    return true
  })

  return (
    <div className="app">
      {toast && <div className="toast-notice">{toast}</div>}

      <aside className="rail">
        <div className="brand">
          <div className="brand-mark">▲ TraceForge</div>
          <div className="brand-title">Product Intelligence</div>
          <div className="brand-sub">
            Web search → Fetch/OCR → BM25 Knowledge Base → Rule Extraction → Self-learning Human Review
          </div>
        </div>

        <div className="panel">
          <div className="panel-label">01 · Input Component List</div>
          <label
            className={`dropzone ${dragActive ? 'drag' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragActive(false)
              handleFile(e.dataTransfer.files[0])
            }}
          >
            <input type="file" accept=".csv,.xlsx" onChange={(e) => handleFile(e.target.files[0])} />
            <div className="dropzone-text">
              {file ? file.name : 'Drop CSV / XLSX or click to browse'}
            </div>
            {uploadInfo && (
              <div className="dropzone-file">
                ✓ {uploadInfo.row_count} rows detected
              </div>
            )}
          </label>
        </div>

        <div className="panel">
          <div className="panel-label">02 · Output Header Template</div>
          <div style={{ fontSize: 11, color: 'var(--ink-faint)', marginBottom: 8, lineHeight: 1.4 }}>
            Defaults to the bundled template. Upload a custom template to override headers.
          </div>
          <label
            className={`dropzone ${templateDragActive ? 'drag' : ''}`}
            style={{ padding: '12px 10px' }}
            onDragOver={(e) => { e.preventDefault(); setTemplateDragActive(true) }}
            onDragLeave={() => setTemplateDragActive(false)}
            onDrop={(e) => {
              e.preventDefault()
              setTemplateDragActive(false)
              handleTemplate(e.dataTransfer.files[0])
            }}
          >
            <input type="file" accept=".csv,.xlsx" onChange={(e) => handleTemplate(e.target.files[0])} />
            <div className="dropzone-text" style={{ fontSize: 11.5 }}>
              {templateFile ? templateFile.name : 'Custom template (optional)'}
            </div>
            {templateInfo && (
              <div className="dropzone-file" style={{ fontSize: 11 }}>
                ✓ {templateInfo.header_count || 'Custom'} headers loaded
              </div>
            )}
          </label>
        </div>

        <div className="panel">
          <div className="panel-label">03 · Run Configuration</div>

          <div className="form-toggle-row">
            <span>Live web search & scraping</span>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={liveMode}
                onChange={(e) => setLiveMode(e.target.checked)}
              />
              <span className="toggle-slider"></span>
            </label>
          </div>

          <div className="field-row-inline" style={{ marginTop: 12 }}>
            <span>Max rows to process</span>
            <input
              type="number"
              min="1"
              max={uploadInfo?.row_count || 5000}
              value={rowLimit}
              onChange={(e) => setRowLimit(e.target.value)}
            />
          </div>

          <div className={`range-control ${!liveMode ? 'disabled' : ''}`}>
            <div className="range-header">
              <span>Row delay (politeness)</span>
              <span className="range-val">{politenessDelay}s</span>
            </div>
            <input
              type="range"
              min="0"
              max="3"
              step="0.5"
              value={politenessDelay}
              disabled={!liveMode}
              onChange={(e) => setPolitenessDelay(e.target.value)}
            />
          </div>

          <div className="form-toggle-row">
            <span>Concurrent processing</span>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={concurrentMode}
                onChange={(e) => setConcurrentMode(e.target.checked)}
              />
              <span className="toggle-slider"></span>
            </label>
          </div>

          <div className={`range-control ${!concurrentMode ? 'disabled' : ''}`}>
            <div className="range-header">
              <span>Worker threads</span>
              <span className="range-val">{maxWorkers} workers</span>
            </div>
            <input
              type="range"
              min="1"
              max="10"
              step="1"
              value={maxWorkers}
              disabled={!concurrentMode}
              onChange={(e) => setMaxWorkers(e.target.value)}
            />
          </div>

          <div className={`form-toggle-row ${!liveMode ? 'disabled' : ''}`}>
            <span>Dynamic 2nd-pass enrichment</span>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={dynamicEnrichment}
                disabled={!liveMode}
                onChange={(e) => setDynamicEnrichment(e.target.checked)}
              />
              <span className="toggle-slider"></span>
            </label>
          </div>

          <div className={`range-control ${(!liveMode || !dynamicEnrichment) ? 'disabled' : ''}`}>
            <div className="range-header">
              <span>Min. missing attributes to trigger</span>
              <span className="range-val">{enrichmentMinMissing} attrs</span>
            </div>
            <input
              type="range"
              min="1"
              max="10"
              step="1"
              value={enrichmentMinMissing}
              disabled={!liveMode || !dynamicEnrichment}
              onChange={(e) => setEnrichmentMinMissing(e.target.value)}
            />
          </div>

          <button
            className="btn btn-primary"
            style={{ marginTop: 10 }}
            disabled={!uploadInfo || busy}
            onClick={handleStart}
          >
            {busy ? 'Processing Batch...' : 'Run pipeline'}
          </button>

          {error && <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 10 }}>{error}</div>}
        </div>

        <div className="panel">
          <div className="panel-label">04 · Self-Learning Cache</div>
          <div className="cache-grid">
            <div className="cache-stat-box">
              <div className="cache-stat-num">{cacheStats.manufacturer_alias}</div>
              <div className="cache-stat-lbl">Brand Aliases</div>
            </div>
            <div className="cache-stat-box">
              <div className="cache-stat-num">{cacheStats.classpath_cache}</div>
              <div className="cache-stat-lbl">Category Rules</div>
            </div>
            <div className="cache-stat-box">
              <div className="cache-stat-num">{cacheStats.source_cache}</div>
              <div className="cache-stat-lbl">Known Sources</div>
            </div>
            <div className="cache-stat-box">
              <div className="cache-stat-num">{cacheStats.correction_log}</div>
              <div className="cache-stat-lbl">Edits Logged</div>
            </div>
          </div>
          <button className="btn btn-ghost" style={{ fontSize: 11 }} onClick={handleResetCacheClick}>
            Reset Learned Cache
          </button>
        </div>

        {job && (
          <div className="panel">
            <div className="panel-label">05 · Job Execution</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-dim)', display: 'flex', justifyContent: 'space-between' }}>
              <span>{job.completed} / {job.total} completed</span>
              {busy && <span className="spinner" />}
            </div>
            <div className="progress-bar-track">
              <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
            </div>
            {activePart && busy && (
              <div style={{ marginTop: 8, fontSize: 11, color: 'var(--ink-faint)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                retrieving: {activePart}
              </div>
            )}

            {logEvents.length > 0 && (
              <div className="sidebar-feed">
                <div className="sidebar-feed-header">
                  <span>RETRIEVED ({logEvents.length})</span>
                  <span>TIME</span>
                </div>
                {logEvents.map((ev, idx) => (
                  <div
                    key={idx}
                    className="feed-item"
                    onClick={() => ev.result?.id && scrollToProduct(ev.result.id)}
                    title="Click to jump to product card"
                  >
                    <div className="feed-item-top">
                      <span className="feed-item-part">{ev.mfg_part_num || `Row #${ev.index + 1}`}</span>
                      <span className="feed-item-time">{ev.elapsed ? `${ev.elapsed}s` : ''}</span>
                    </div>
                    {ev.part_desc && <div className="feed-item-desc">{ev.part_desc}</div>}
                    <div className="feed-item-meta">
                      <span>{ev.fields_populated || (ev.result?.data ? getFieldsPopulated(ev.result.data) : 0)} fields</span>
                      {ev.needs_review && <span className="feed-flag-badge">⚠️ REVIEW</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {job && job.status === 'done' && (
          <div className="panel">
            <div className="panel-label">06 · Output Exports</div>
            <div className="action-row" style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 8 }}>
              <a className="btn btn-primary" href={exportUrl(job.job_id, 'xlsx')}>
                Download XLSX (confidence-highlighted)
              </a>
              <a className="btn btn-ghost" href={exportUrl(job.job_id, 'csv')}>
                Download CSV
              </a>
              <a className="btn btn-ghost" href={exportReviewLogUrl(job.job_id)}>
                Download Review Log CSV
              </a>
            </div>
            <button className="btn" style={{ marginTop: 10 }} onClick={handleEvaluate}>
              Evaluate Accuracy Against Ground Truth
            </button>
          </div>
        )}
      </aside>

      <main className="main">
        <div className="topbar">
          <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
            <h1>Product Intelligence Console</h1>
            <div className="view-mode-selector">
              <button className={`tab-btn ${viewMode === 'all' ? 'active' : ''}`} onClick={() => setViewMode('all')}>
                All Products ({results.length})
              </button>
              <button className={`tab-btn ${viewMode === 'review_queue' ? 'active' : ''}`} onClick={() => setViewMode('review_queue')}>
                Review Queue {reviewCount > 0 && <span className="count-badge">{reviewCount}</span>}
              </button>
            </div>
          </div>
          <div className="topbar-meta">
            {job ? `Job: ${job.job_id.slice(0, 8)} · ${job.status}` : 'No active batch'}
          </div>
        </div>

        {viewMode === 'review_queue' && (
          reviewCount > 0 ? (
            <div className="banner banner-warning">
              <span>
                ⚠️ <strong>Human-in-the-Loop Review Queue:</strong> Showing {reviewCount} product(s) with low-confidence fields. Approving or correcting Manufacturer/Brand or Category will auto-propagate to matching sibling SKUs in this batch.
              </span>
            </div>
          ) : (
            <div className="banner banner-success" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>✓ All products in this batch have high confidence. Nothing flagged for human review!</span>
              <button className="btn btn-ghost" style={{ padding: '4px 10px', fontSize: 11 }} onClick={() => setViewMode('all')}>View All Products</button>
            </div>
          )
        )}

        {lastRunLive === false && (
          <div className="banner banner-warning">
            <span>
              ⚠️ Last run was in <strong>offline/cache-only mode</strong> — DuckDuckGo and live scraping were disabled. Most fields will be blank unless previously cached. Toggle Live mode ON and re-run for complete web enrichment.
            </span>
          </div>
        )}

        {results.length > 0 && (
          <div className="stat-strip">
            <div className="stat-card">
              <div className="stat-value">{results.length}</div>
              <div className="stat-label">Total batch</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{completedCount}</div>
              <div className="stat-label">Completed</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: failedCount > 0 ? 'var(--red)' : 'inherit' }}>{failedCount}</div>
              <div className="stat-label">Failed</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{Math.round(avgConf * 100)}%</div>
              <div className="stat-label">Avg Confidence</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: reviewCount > 0 ? 'var(--amber)' : 'inherit' }}>{reviewCount}</div>
              <div className="stat-label">Needs Review</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{avgFields}</div>
              <div className="stat-label">Avg Fields Filled</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{avgTime}s</div>
              <div className="stat-label">Avg Row Time</div>
            </div>
            {job?.batch_stats?.cache_hit_rate !== undefined && (
              <div className="stat-card">
                <div className="stat-value">{Math.round(job.batch_stats.cache_hit_rate * 100)}%</div>
                <div className="stat-label">Cache Hit Rate</div>
              </div>
            )}
            {evaluation && (
              <>
                <div className="stat-card">
                  <div className="stat-value">{evaluation.overall_accuracy_pct}%</div>
                  <div className="stat-label">Eval Accuracy</div>
                </div>
                <div className="stat-card">
                  <div className="stat-value">{evaluation.overall_completeness_pct}%</div>
                  <div className="stat-label">Completeness</div>
                </div>
              </>
            )}
          </div>
        )}

        {results.length > 0 && (
          <OverviewTable
            results={viewMode === 'review_queue' ? filteredResults : results}
            onSelect={scrollToProduct}
          />
        )}

        {results.length > 0 && (
          <div className="filter-bar">
            <div className="filter-item">
              <label>Status</label>
              <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
                <option value="all">All</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
              </select>
            </div>
            <div className="filter-item">
              <label>Category</label>
              <select value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}>
                {categories.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div className="filter-item">
              <label>Confidence</label>
              <select value={filterConfidence} onChange={(e) => setFilterConfidence(e.target.value)}>
                <option value="all">All</option>
                <option value="high">High (&gt;80%)</option>
                <option value="mid">Mid (55%-80%)</option>
                <option value="low">Low (&lt;55%)</option>
              </select>
            </div>
            <div className="filter-item">
              <label>Review</label>
              <select value={filterReview} onChange={(e) => setFilterReview(e.target.value)}>
                <option value="all">All</option>
                <option value="needs_review">Needs Review</option>
                <option value="approved">Approved</option>
              </select>
            </div>
          </div>
        )}

        {filteredResults.length === 0 ? (
          <div className="empty-state">
            {results.length === 0 ? (
              <>
                <h2>No products loaded yet</h2>
                <p>
                  Upload your inventory dataset on the left and configure your pipeline settings to start high-throughput taxonomy and attribute enrichment.
                </p>
              </>
            ) : viewMode === 'review_queue' ? (
              <>
                <h2>Review Queue is Empty</h2>
                <p>All products in this batch passed confidence thresholds and are approved.</p>
              </>
            ) : (
              <>
                <h2>No matches found</h2>
                <p>Try clearing or relaxing your filter parameters.</p>
              </>
            )}
          </div>
        ) : (
          <div className="products-list">
            {filteredResults.map((r) => (
              <div id={`prod-${r.id}`} key={r.id}>
                <ProductCard
                  result={r}
                  jobId={job?.job_id}
                  onEdited={handleEdit}
                  getFieldsPopulatedCount={getFieldsPopulated}
                  forceOpen={viewMode === 'review_queue'}
                  initialTab={viewMode === 'review_queue' ? 'review' : 'identity'}
                />
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
