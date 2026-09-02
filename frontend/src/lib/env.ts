function required(name: string): string {
  const value = import.meta.env[name]
  if (!value) throw new Error(`Missing required environment variable: ${name}`)
  return value
}

export const env = {
  apiBaseUrl: required('VITE_API_BASE_URL'),
  allowedEmailDomain: required('VITE_ALLOWED_EMAIL_DOMAIN').toLowerCase(),
  supabaseAnonKey: required('VITE_SUPABASE_ANON_KEY'),
  supabaseUrl: required('VITE_SUPABASE_URL'),
}
