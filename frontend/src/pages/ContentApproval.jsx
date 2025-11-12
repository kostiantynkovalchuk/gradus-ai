import { useState, useEffect } from 'react'
import { CheckCircle, XCircle, Edit, Eye, Calendar } from 'lucide-react'
import axios from 'axios'

const API_URL = window.location.origin.replace(':5000', ':8000')

function ContentApproval() {
  const [pendingContent, setPendingContent] = useState([])
  const [stats, setStats] = useState({ pending: 0, approved: 0, posted: 0, rejected: 0 })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const [contentRes, statsRes] = await Promise.all([
        axios.get(`${API_URL}/api/content/pending`),
        axios.get(`${API_URL}/api/content/stats`)
      ])
      setPendingContent(contentRes.data)
      setStats(statsRes.data)
    } catch (error) {
      console.error('Error fetching data:', error)
    }
    setLoading(false)
  }

  const handleApprove = async (contentId) => {
    try {
      await axios.post(`${API_URL}/api/content/${contentId}/approve`, {
        moderator: 'Admin',
        platforms: ['facebook', 'linkedin']
      })
      fetchData()
    } catch (error) {
      console.error('Error approving content:', error)
    }
  }

  const handleReject = async (contentId) => {
    const reason = prompt('Reason for rejection:')
    if (!reason) return

    try {
      await axios.post(`${API_URL}/api/content/${contentId}/reject`, {
        moderator: 'Admin',
        reason: reason
      })
      fetchData()
    } catch (error) {
      console.error('Error rejecting content:', error)
    }
  }

  if (loading) {
    return <div className="text-center py-8">Loading...</div>
  }

  return (
    <div>
      <h1 className="text-3xl font-bold text-gray-900 mb-6">Content Approval</h1>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="text-sm text-yellow-700">Pending</div>
          <div className="text-2xl font-bold text-yellow-900">{stats.pending}</div>
        </div>
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <div className="text-sm text-green-700">Approved</div>
          <div className="text-2xl font-bold text-green-900">{stats.approved}</div>
        </div>
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="text-sm text-blue-700">Posted</div>
          <div className="text-2xl font-bold text-blue-900">{stats.posted}</div>
        </div>
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="text-sm text-red-700">Rejected</div>
          <div className="text-2xl font-bold text-red-900">{stats.rejected}</div>
        </div>
      </div>

      {pendingContent.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center">
          <p className="text-gray-500">No content pending approval</p>
          <p className="text-sm text-gray-400 mt-2">New content from the news scraper will appear here</p>
        </div>
      ) : (
        <div className="space-y-4">
          {pendingContent.map((content) => (
            <div key={content.id} className="bg-white rounded-lg shadow p-6">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h3 className="text-lg font-semibold">{content.source_title || 'Untitled'}</h3>
                  <p className="text-sm text-gray-500">Source: {content.source}</p>
                </div>
                <span className="px-3 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                  Pending
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div>
                  <p className="text-sm font-medium text-gray-700 mb-2">Original (English):</p>
                  <div className="p-3 bg-gray-50 rounded text-sm">
                    {content.original_text || 'No content'}
                  </div>
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-700 mb-2">Translation (Ukrainian):</p>
                  <div className="p-3 bg-gray-50 rounded text-sm">
                    {content.translated_text || 'No translation'}
                  </div>
                </div>
              </div>

              {content.image_url && (
                <div className="mb-4">
                  <p className="text-sm font-medium text-gray-700 mb-2">Generated Image:</p>
                  <img src={content.image_url} alt="Generated" className="max-w-md rounded" />
                </div>
              )}

              <div className="flex space-x-2">
                <button
                  onClick={() => handleApprove(content.id)}
                  className="flex items-center space-x-1 px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
                >
                  <CheckCircle size={16} />
                  <span>Approve</span>
                </button>
                <button
                  onClick={() => handleReject(content.id)}
                  className="flex items-center space-x-1 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
                >
                  <XCircle size={16} />
                  <span>Reject</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default ContentApproval
