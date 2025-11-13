const getApiUrl = () => {
  if (typeof window === 'undefined') return '/api'
  
  return '/api'
}

export const API_URL = getApiUrl()

console.log('API URL configured (proxied):', API_URL)
