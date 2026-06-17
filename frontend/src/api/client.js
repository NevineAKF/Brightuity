/**
 * api/client.js — single source of all backend calls.
 *
 * Base URL is read from VITE_API_BASE env var:
 *   .env.development  → http://95.179.206.209:8000   (Vultr live backend)
 *   .env.production   → (empty) same-origin via nginx proxy
 *
 * No page should call fetch() directly — import from here.
 */

const BASE = import.meta.env.VITE_API_BASE ?? 'http://95.179.206.209:8000'

/**
 * Internal fetch wrapper. Throws an Error with `.status` on non-OK responses.
 * @param {'GET'|'POST'} method
 * @param {string} path
 * @param {object} [body]
 * @returns {Promise<any>}
 */
async function request(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res = await fetch(`${BASE}${path}`, opts)
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch (_) {}
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

/**
 * GET /cases — return the dashboard queue.
 * @param {string} [status] - 'pending' | 'all' | any lifecycle status
 * @returns {Promise<Array<object>>}
 */
export async function getCases(status) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return request('GET', `/cases${qs}`)
}

/**
 * POST /cases/{id}/run — trigger the compliance pipeline.
 * @param {string} requestId
 * @param {{ force?: boolean }} [opts]
 * @returns {Promise<object>}
 */
export async function runCase(requestId, { force = false } = {}) {
  return request('POST', `/cases/${encodeURIComponent(requestId)}/run?force=${force}`)
}

/**
 * GET /cases/{id}/status — poll pipeline lifecycle status.
 * @param {string} requestId
 * @returns {Promise<object>}
 */
export async function getCaseStatus(requestId) {
  return request('GET', `/cases/${encodeURIComponent(requestId)}/status`)
}

/**
 * GET /cases/{id}/package — retrieve the full Decision Evidence Package.
 * @param {string} requestId
 * @returns {Promise<object>}
 */
export async function getEvidencePackage(requestId) {
  return request('GET', `/cases/${encodeURIComponent(requestId)}/package`)
}

/**
 * Build the direct URL for the evidence PDF (use with <a href> or window.open).
 * @param {string} requestId
 * @param {{ download?: boolean }} [opts]
 * @returns {string}
 */
export function evidencePdfUrl(requestId, { download = false } = {}) {
  return `${BASE}/cases/${encodeURIComponent(requestId)}/evidence.pdf?download=${download}`
}

/**
 * POST /cases/{id}/authorize — record the human Approve/Reject decision.
 * @param {string} requestId
 * @param {{ decision: string, rationale: string, signatory_name: string, signatory_role: string, annotations?: string[] }} payload
 * @returns {Promise<object>}
 */
export async function authorizeCase(requestId, payload) {
  return request('POST', `/cases/${encodeURIComponent(requestId)}/authorize`, payload)
}

/**
 * GET /cases/{id}/band-messages — fetch live Band coordination room messages.
 * @param {string} requestId
 * @returns {Promise<{ request_id: string, chat_id: string|null, messages: object[], status: string, error?: string }>}
 */
export async function getBandMessages(requestId) {
  return request('GET', `/cases/${encodeURIComponent(requestId)}/band-messages`)
}
