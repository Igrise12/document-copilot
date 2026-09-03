function required(name: string): string {
  const value = import.meta.env[name]
  if (!value) throw new Error(`Missing required environment variable: ${name}`)
  return value
}

function positiveInteger(name: string): number {
  const value = Number(required(name))
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer`)
  return value
}

export const env = {
  apiBaseUrl: required('VITE_API_BASE_URL'),
  allowedEmailDomain: required('VITE_ALLOWED_EMAIL_DOMAIN').toLowerCase(),
  maxUploadBytes: positiveInteger('VITE_MAX_UPLOAD_BYTES'),
  supabaseAnonKey: required('VITE_SUPABASE_ANON_KEY'),
  supabaseUrl: required('VITE_SUPABASE_URL'),
}
