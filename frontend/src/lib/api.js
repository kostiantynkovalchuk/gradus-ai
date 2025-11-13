import axios from 'axios'

const getApiUrl = () => {
  if (typeof window === 'undefined') return '/api'
  
  return '/api'
}

export const API_URL = getApiUrl()

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

console.log('API URL configured (proxied):', API_URL)

export default api
