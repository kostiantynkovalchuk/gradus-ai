const getApiUrl = () => {
  if (typeof window === 'undefined') return 'http://localhost:8000'
  
  const hostname = window.location.hostname
  const protocol = window.location.protocol
  
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return 'http://localhost:8000'
  }
  
  if (hostname.includes('replit.dev') || hostname.includes('repl.co')) {
    const baseHost = hostname.split('.')[0]
    const domain = hostname.split('.').slice(-2).join('.')
    return `${protocol}//${baseHost}.${domain}`.replace(/:\d+/, '').replace(/-5000/, '-8000')
  }
  
  return window.location.origin.replace(':5000', ':8000')
}

export const API_URL = getApiUrl()

console.log('API URL configured:', API_URL)
