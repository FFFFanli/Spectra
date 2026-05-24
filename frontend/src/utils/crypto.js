const KEY_MATERIAL = [
  navigator.userAgent,
  screen.width + 'x' + screen.height + 'x' + screen.colorDepth,
  Intl.DateTimeFormat().resolvedOptions().timeZone,
  navigator.language
].join('|')

const PBKDF2_ITERATIONS = 200000
const SALT_LENGTH = 16
const IV_LENGTH = 12
const KEY_LENGTH = 256

async function deriveKey(salt) {
  const enc = new TextEncoder()
  const baseKey = await crypto.subtle.importKey(
    'raw', enc.encode(KEY_MATERIAL),
    'PBKDF2', false, ['deriveKey']
  )
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt, iterations: PBKDF2_ITERATIONS, hash: 'SHA-256' },
    baseKey,
    { name: 'AES-GCM', length: KEY_LENGTH },
    false,
    ['encrypt', 'decrypt']
  )
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
}

function base64ToArrayBuffer(base64) {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer
}

export async function encrypt(plaintext) {
  if (!plaintext) return ''
  const salt = crypto.getRandomValues(new Uint8Array(SALT_LENGTH))
  const iv = crypto.getRandomValues(new Uint8Array(IV_LENGTH))
  const key = await deriveKey(salt)
  const enc = new TextEncoder()
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    enc.encode(plaintext)
  )
  const combined = new Uint8Array(salt.length + iv.length + ciphertext.byteLength)
  combined.set(salt, 0)
  combined.set(iv, salt.length)
  combined.set(new Uint8Array(ciphertext), salt.length + iv.length)
  return arrayBufferToBase64(combined.buffer)
}

export async function decrypt(cipherBase64) {
  if (!cipherBase64) return ''
  try {
    const combined = new Uint8Array(base64ToArrayBuffer(cipherBase64))
    const salt = combined.slice(0, SALT_LENGTH)
    const iv = combined.slice(SALT_LENGTH, SALT_LENGTH + IV_LENGTH)
    const ciphertext = combined.slice(SALT_LENGTH + IV_LENGTH)
    const key = await deriveKey(salt)
    const dec = new TextDecoder()
    const plaintext = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      key,
      ciphertext
    )
    return dec.decode(plaintext)
  } catch (e) {
    return ''
  }
}

export function maskKey(key) {
  if (!key || key.length <= 8) return key ? '***' : ''
  return key.slice(0, 4) + '****' + key.slice(-4)
}
