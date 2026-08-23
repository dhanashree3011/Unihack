const BASE = import.meta.env.VITE_API_URL || '/api'
export async function uploadFile(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error((await res.json()).detail || 'Upload failed')
  return res.json()
}

export async function uploadTemplate(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/upload_template`, { method: 'POST', body: form })
  if (!res.ok) throw new Error((await res.json()).detail || 'Template upload failed')
  return res.json()
}

export async function startJob(uploadId, opts = {}) {
  const params = new URLSearchParams({ upload_id: uploadId })
  if (opts.rowLimit)             params.append('row_limit', opts.rowLimit)
  if (opts.live !== undefined)   params.append('live', opts.live)
  if (opts.politenessDelay !== undefined) params.append('politeness_delay', opts.politenessDelay)
  if (opts.concurrent !== undefined)      params.append('concurrent', opts.concurrent)
  if (opts.maxWorkers !== undefined)      params.append('max_workers', opts.maxWorkers)
  if (opts.dynamicEnrichment !== undefined) params.append('dynamic_enrichment', opts.dynamicEnrichment)
  if (opts.enrichmentMinMissing !== undefined) params.append('enrichment_min_missing', opts.enrichmentMinMissing)
  if (opts.templateUploadId)     params.append('template_upload_id', opts.templateUploadId)

  const res = await fetch(`${BASE}/jobs?${params}`, { method: 'POST' })
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to start job')
  return res.json()
}

export async function getJob(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}`)
  return res.json()
}

export async function getResults(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}/results`)
  return res.json()
}

export async function editResult(jobId, resultId, fieldPath, value) {
  const res = await fetch(`${BASE}/jobs/${jobId}/results/${resultId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ field_path: fieldPath, value }),
  })
  return res.json()
}

export async function getEvaluation(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}/evaluate`)
  return res.json()
}

export function exportUrl(jobId, fmt) {
  return `${BASE}/jobs/${jobId}/export?fmt=${fmt}`
}

export function exportReviewLogUrl(jobId) {
  return `${BASE}/jobs/${jobId}/export?fmt=review_log`
}

export function streamJob(jobId, onEvent) {
  const es = new EventSource(`${BASE}/jobs/${jobId}/stream`)
  es.onmessage = (e) => {
    const data = JSON.parse(e.data)
    onEvent(data)
    if (data.type === 'job_done') es.close()
  }
  es.onerror = () => es.close()
  return () => es.close()
}
export async function getCacheStats() {
  const res = await fetch(`${BASE}/cache/stats`)
  if (!res.ok) return null
  return res.json()
}

export async function resetCache() {
  const res = await fetch(`${BASE}/cache`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Cache reset failed')
  return res.json()
}
