export async function* parseSSEStream(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        // 流结束：处理 buffer 中残余的最后一条事件
        if (buffer.trim()) {
          buffer = buffer.replace(/\r\n/g, '\n')
          const lines = buffer.split('\n')
          let eventType = 'message'
          let dataStr = ''
          for (const l of lines) {
            if (l.startsWith('event: ')) eventType = l.substring(7).trim()
            else if (l.startsWith('data: ')) dataStr += l.substring(6)
          }
          if (dataStr) {
            let parsed
            try { parsed = JSON.parse(dataStr) } catch { parsed = dataStr }
            yield { event: eventType, data: parsed }
          }
        }
        break
      }

      buffer += decoder.decode(value, { stream: true })
      buffer = buffer.replace(/\r\n/g, '\n')
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      for (const part of parts) {
        if (!part.trim()) continue
        const lines = part.split('\n')
        let eventType = 'message'
        let dataStr = ''

        for (const l of lines) {
          if (l.startsWith('event: ')) eventType = l.substring(7).trim()
          else if (l.startsWith('data: ')) dataStr += l.substring(6)
        }
        if (!dataStr) continue

        // [Spectra debug] 记录每个收到的 SSE 事件
        console.log('[Spectra SSE] recv event:', eventType, 'dataLen:', dataStr.length)

        let parsed
        try { parsed = JSON.parse(dataStr) } catch { parsed = dataStr }
        yield { event: eventType, data: parsed }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export function getAccessCode() {
  return localStorage.getItem('spectra_access_code') || ''
}

export function setAccessCode(code) {
  if (code) {
    localStorage.setItem('spectra_access_code', code)
  } else {
    localStorage.removeItem('spectra_access_code')
  }
}

function authHeaders() {
  const code = getAccessCode()
  return code ? { 'Authorization': `Bearer ${code}` } : {}
}

export async function streamFetch(url, body, signal) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response
}

export async function apiFetch(url, options = {}) {
  const { headers = {}, ...rest } = options
  const response = await fetch(url, {
    ...rest,
    headers: { ...headers, ...authHeaders() },
  })
  if (!response.ok) {
    const errData = await response.json().catch(() => ({}))
    const msg = errData.error || errData.detail || `HTTP ${response.status}`
    throw new Error(msg)
  }
  return response
}
