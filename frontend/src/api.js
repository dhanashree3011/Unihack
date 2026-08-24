const configuredBase = import.meta.env.VITE_API_URL?.replace(/\/+$/, '')
const BASE = configuredBase
  ? (configuredBase.endsWith('/api') ? configuredBase : `${configuredBase}/api`)
  : '/api'

async function readJsonResponse(res, fallbackMessage) {
  const body = await res.text()
  let payload
  try {
    payload = body ? JSON.parse(body) : null
  } catch {
    payload = null
  }

  if (!res.ok) {
    const detail = payload?.detail || body.replace(/\s+/g, ' ').trim().slice(0, 180)
    throw new Error(`${fallbackMessage} (${res.status})${detail ? `: ${detail}` : ''}`)
  }

  return payload
}

async function fetchJson(url, options, fallbackMessage) {
  let res
  try {
    res = await fetch(url, options)
  } catch (error) {
    throw new Error(`${fallbackMessage}: cannot reach ${url}. ${error.message}`)
  }
  return readJsonResponse(res, fallbackMessage)
}

export async function uploadFile(file) {
  const form = new FormData()
  form.append('file', file)
  return fetchJson(`${BASE}/upload`, { method: 'POST', body: form }, 'Upload failed')
}

export async function uploadTemplate(file) {
  const form = new FormData()
  form.append('file', file)
  return fetchJson(`${BASE}/upload_template`, { method: 'POST', body: form }, 'Template upload failed')
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

  return fetchJson(`${BASE}/jobs?${params}`, { method: 'POST' }, 'Failed to start job')
}

export async function getJob(jobId) {
  return fetchJson(`${BASE}/jobs/${jobId}`, undefined, 'Failed to load job')
}

export async function getResults(jobId) {
  return fetchJson(`${BASE}/jobs/${jobId}/results`, undefined, 'Failed to load results')
}

export async function editResult(jobId, resultId, fieldPath, value) {
  return fetchJson(`${BASE}/jobs/${jobId}/results/${resultId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ field_path: fieldPath, value }),
  }, 'Failed to save edit')
}

export async function getEvaluation(jobId) {
  return fetchJson(`${BASE}/jobs/${jobId}/evaluate`, undefined, 'Failed to load evaluation')
}

export function exportUrl(jobId, fmt) {
  return `${BASE}/jobs/${jobId}/export?fmt=${fmt}`
}

export function exportReviewLogUrl(jobId) {
  return `${BASE}/jobs/${jobId}/export?fmt=review_log`
}

export function streamJob(jobId, onEvent, onError) {
  const es = new EventSource(`${BASE}/jobs/${jobId}/stream`)
  es.onmessage = (e) => {
    const data = JSON.parse(e.data)
    onEvent(data)
    if (data.type === 'job_done') es.close()
  }
  es.onerror = () => {
    es.close()
    onError?.(new Error(`Live progress unavailable at ${BASE}/jobs/${jobId}/stream`))
  }
  return () => es.close()
}
export async function getCacheStats() {
  const res = await fetch(`${BASE}/cache/stats`)
  if (!res.ok) return null
  return readJsonResponse(res, 'Failed to load cache stats')
}

export async function resetCache() {
  const res = await fetch(`${BASE}/cache`, { method: 'DELETE' })
  return readJsonResponse(res, 'Cache reset failed')
}
