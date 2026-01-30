import { useState, useEffect, useCallback } from 'react'
import { Search, Trash2, Eye, Download, RefreshCw, AlertTriangle, CheckCircle, X, ChevronLeft, ChevronRight, ImageIcon, Loader2 } from 'lucide-react'
import api from '../lib/api'

function StatCard({ label, value, colorClass }) {
  return (
    <div className="glass-card p-3 text-center">
      <div className={`text-xs ${colorClass} opacity-70`}>{label}</div>
      <div className={`text-xl font-bold ${colorClass}`}>{value}</div>
    </div>
  )
}

function ArticleManager() {
  const [articles, setArticles] = useState([])
  const [stats, setStats] = useState({ total: 0, pending: 0, approved: 0, posted: 0, rejected: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const limit = 20
  
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [selectedArticle, setSelectedArticle] = useState(null)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [articleToDelete, setArticleToDelete] = useState(null)
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false)
  const [toast, setToast] = useState(null)
  const [fetchingImage, setFetchingImage] = useState(false)

  const showToast = (message, type = 'success') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 4000)
  }

  const fetchArticles = useCallback(async () => {
    setLoading(true)
    setError(null)
    
    try {
      const params = new URLSearchParams()
      params.append('limit', limit)
      params.append('offset', offset)
      if (search) params.append('search', search)
      if (statusFilter) params.append('status', statusFilter)
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      
      const response = await api.get(`/admin/articles?${params}`)
      setArticles(response.data.articles)
      setTotal(response.data.total)
      setStats(response.data.stats)
    } catch (err) {
      setError('Failed to load articles')
      console.error('Error fetching articles:', err)
    }
    setLoading(false)
  }, [offset, search, statusFilter, dateFrom, dateTo])

  useEffect(() => {
    fetchArticles()
  }, [fetchArticles])

  const handleSearch = (e) => {
    e.preventDefault()
    setOffset(0)
    fetchArticles()
  }

  const handleViewArticle = async (articleId) => {
    try {
      const response = await api.get(`/admin/articles/${articleId}`)
      setSelectedArticle(response.data)
    } catch (err) {
      showToast('Failed to load article details', 'error')
    }
  }

  const handleDeleteClick = (article) => {
    setArticleToDelete(article)
    setDeleteConfirmText('')
    setShowDeleteModal(true)
  }

  const handleDeleteConfirm = async () => {
    if (deleteConfirmText !== 'DELETE') return
    
    try {
      await api.delete(`/admin/articles/${articleToDelete.id}`)
      showToast(`Deleted: ${articleToDelete.title}`)
      setShowDeleteModal(false)
      setArticleToDelete(null)
      fetchArticles()
    } catch (err) {
      showToast('Failed to delete article', 'error')
    }
  }

  const handleBulkDelete = async () => {
    if (deleteConfirmText !== 'DELETE') return
    
    try {
      const response = await api.post('/admin/articles/bulk-delete', {
        article_ids: Array.from(selectedIds)
      })
      showToast(`Deleted ${response.data.deleted_count} articles`)
      setShowBulkDeleteModal(false)
      setSelectedIds(new Set())
      setDeleteConfirmText('')
      fetchArticles()
    } catch (err) {
      showToast('Failed to delete articles', 'error')
    }
  }

  const handleFetchImage = async (articleId) => {
    setFetchingImage(true)
    try {
      const response = await api.post(`/admin/articles/${articleId}/fetch-image`)
      showToast('Image fetched successfully from Unsplash')
      setSelectedArticle(prev => ({
        ...prev,
        image_url: response.data.image_url,
        image_credit: response.data.image_credit,
        image_credit_url: response.data.image_credit_url,
        image_photographer: response.data.image_photographer,
        has_image: true
      }))
      fetchArticles()
    } catch (err) {
      const message = err.response?.data?.detail || 'Failed to fetch image'
      showToast(message, 'error')
    }
    setFetchingImage(false)
  }

  const handleExport = async () => {
    try {
      const params = new URLSearchParams()
      if (search) params.append('search', search)
      if (statusFilter) params.append('status', statusFilter)
      if (dateFrom) params.append('date_from', dateFrom)
      if (dateTo) params.append('date_to', dateTo)
      
      window.open(`/api/admin/articles/export/csv?${params}`, '_blank')
      showToast('Export started')
    } catch (err) {
      showToast('Failed to export', 'error')
    }
  }

  const toggleSelect = (id) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }
    setSelectedIds(newSelected)
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === articles.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(articles.map(a => a.id)))
    }
  }

  const getPlatformIcons = (platforms) => {
    if (!platforms || platforms.length === 0) return '—'
    const icons = []
    if (platforms.includes('facebook')) icons.push('📱')
    if (platforms.includes('linkedin')) icons.push('💼')
    if (platforms.includes('telegram')) icons.push('✈️')
    return icons.join(' ') || '—'
  }

  const getStatusBadge = (status) => {
    const colors = {
      'pending_approval': 'bg-yellow-500/20 text-yellow-300',
      'approved': 'bg-blue-500/20 text-blue-300',
      'posted': 'bg-green-500/20 text-green-300',
      'rejected': 'bg-red-500/20 text-red-300'
    }
    return (
      <span className={`px-2 py-1 rounded-full text-xs ${colors[status] || 'bg-gray-500/20 text-gray-300'}`}>
        {status?.replace('_', ' ') || 'unknown'}
      </span>
    )
  }

  const totalPages = Math.ceil(total / limit)
  const currentPage = Math.floor(offset / limit) + 1

  return (
    <div className="space-y-6">
      {toast && (
        <div className={`fixed top-20 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 ${
          toast.type === 'error' ? 'bg-red-500' : 'bg-green-500'
        } text-white`}>
          {toast.type === 'error' ? <AlertTriangle size={18} /> : <CheckCircle size={18} />}
          {toast.message}
        </div>
      )}

      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold gradient-text">Article Manager</h1>
        <div className="flex gap-2">
          <button 
            onClick={handleExport}
            className="btn-secondary flex items-center gap-2"
          >
            <Download size={16} />
            Export
          </button>
          <button 
            onClick={fetchArticles}
            className="btn-secondary flex items-center gap-2"
          >
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-5 gap-3">
        <StatCard label="Total" value={stats.total} colorClass="text-white" />
        <StatCard label="Pending" value={stats.pending} colorClass="text-yellow-400" />
        <StatCard label="Approved" value={stats.approved} colorClass="text-blue-400" />
        <StatCard label="Posted" value={stats.posted} colorClass="text-green-400" />
        <StatCard label="Rejected" value={stats.rejected} colorClass="text-red-400" />
      </div>

      <div className="glass-card p-4">
        <form onSubmit={handleSearch} className="flex flex-wrap gap-3">
          <div className="flex-1 min-w-[200px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-white/50" size={18} />
              <input
                type="text"
                placeholder="Search articles..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>
          
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setOffset(0); }}
            className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:border-blue-500 focus:outline-none"
          >
            <option value="">All Status</option>
            <option value="pending_approval">Pending</option>
            <option value="approved">Approved</option>
            <option value="posted">Posted</option>
            <option value="rejected">Rejected</option>
          </select>
          
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => { setDateFrom(e.target.value); setOffset(0); }}
            className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:border-blue-500 focus:outline-none"
          />
          
          <input
            type="date"
            value={dateTo}
            onChange={(e) => { setDateTo(e.target.value); setOffset(0); }}
            className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:border-blue-500 focus:outline-none"
          />
          
          <button type="submit" className="btn-primary">
            Search
          </button>
        </form>
      </div>

      {selectedIds.size > 0 && (
        <div className="glass-card p-3 flex items-center justify-between bg-red-500/10 border-red-500/30">
          <span className="text-white">{selectedIds.size} articles selected</span>
          <button 
            onClick={() => { setDeleteConfirmText(''); setShowBulkDeleteModal(true); }}
            className="btn-danger flex items-center gap-2"
          >
            <Trash2 size={16} />
            Delete Selected
          </button>
        </div>
      )}

      <div className="glass-card overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-white/50">Loading...</div>
        ) : error ? (
          <div className="p-8 text-center text-red-400">{error}</div>
        ) : articles.length === 0 ? (
          <div className="p-8 text-center text-white/50">No articles found</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-white/5">
                <tr>
                  <th className="px-4 py-3 text-left">
                    <input 
                      type="checkbox" 
                      checked={selectedIds.size === articles.length && articles.length > 0}
                      onChange={toggleSelectAll}
                      className="rounded"
                    />
                  </th>
                  <th className="px-4 py-3 text-left text-white/70 text-sm">ID</th>
                  <th className="px-4 py-3 text-left text-white/70 text-sm">Title</th>
                  <th className="px-4 py-3 text-left text-white/70 text-sm">Status</th>
                  <th className="px-4 py-3 text-left text-white/70 text-sm">Platforms</th>
                  <th className="px-4 py-3 text-left text-white/70 text-sm">Date</th>
                  <th className="px-4 py-3 text-left text-white/70 text-sm">Actions</th>
                </tr>
              </thead>
              <tbody>
                {articles.map((article) => (
                  <tr key={article.id} className="border-t border-white/5 hover:bg-white/5">
                    <td className="px-4 py-3">
                      <input 
                        type="checkbox" 
                        checked={selectedIds.has(article.id)}
                        onChange={() => toggleSelect(article.id)}
                        className="rounded"
                      />
                    </td>
                    <td className="px-4 py-3 text-white/70 text-sm">{article.id}</td>
                    <td className="px-4 py-3 text-white text-sm max-w-xs truncate">
                      {article.title || 'Untitled'}
                    </td>
                    <td className="px-4 py-3">{getStatusBadge(article.status)}</td>
                    <td className="px-4 py-3 text-sm">{getPlatformIcons(article.platforms)}</td>
                    <td className="px-4 py-3 text-white/70 text-sm">
                      {article.created_at ? new Date(article.created_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button 
                          onClick={() => handleViewArticle(article.id)}
                          className="p-1.5 hover:bg-white/10 rounded text-blue-400"
                          title="View"
                        >
                          <Eye size={16} />
                        </button>
                        <button 
                          onClick={() => handleDeleteClick(article)}
                          className="p-1.5 hover:bg-white/10 rounded text-red-400"
                          title="Delete"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        
        {total > limit && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-white/5">
            <span className="text-white/50 text-sm">
              Showing {offset + 1}-{Math.min(offset + limit, total)} of {total}
            </span>
            <div className="flex gap-2">
              <button 
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
                className="p-2 hover:bg-white/10 rounded disabled:opacity-30"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="px-3 py-1 text-white/70">
                Page {currentPage} of {totalPages}
              </span>
              <button 
                onClick={() => setOffset(offset + limit)}
                disabled={offset + limit >= total}
                className="p-2 hover:bg-white/10 rounded disabled:opacity-30"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
        )}
      </div>

      {selectedArticle && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="glass-card max-w-2xl w-full max-h-[80vh] overflow-y-auto p-6">
            <div className="flex justify-between items-start mb-4">
              <h2 className="text-xl font-bold text-white">Article Details</h2>
              <button onClick={() => setSelectedArticle(null)} className="text-white/50 hover:text-white">
                <X size={24} />
              </button>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="text-white/50 text-sm">ID</label>
                <p className="text-white">{selectedArticle.id}</p>
              </div>
              <div>
                <label className="text-white/50 text-sm">Title</label>
                <p className="text-white">{selectedArticle.title || 'Untitled'}</p>
              </div>
              <div>
                <label className="text-white/50 text-sm">Status</label>
                <p>{getStatusBadge(selectedArticle.status)}</p>
              </div>
              <div>
                <label className="text-white/50 text-sm">Source</label>
                <p className="text-white">{selectedArticle.source || '—'}</p>
              </div>
              <div>
                <label className="text-white/50 text-sm">Category</label>
                <p className="text-white">{selectedArticle.category || '—'}</p>
              </div>
              <div>
                <label className="text-white/50 text-sm">Content Preview</label>
                <p className="text-white/70 text-sm max-h-40 overflow-y-auto">
                  {selectedArticle.content?.slice(0, 500) || 'No content'}...
                </p>
              </div>
              {selectedArticle.source_url && (
                <div>
                  <label className="text-white/50 text-sm">Source URL</label>
                  <a href={selectedArticle.source_url} target="_blank" rel="noopener noreferrer" 
                     className="text-blue-400 hover:underline block truncate">
                    {selectedArticle.source_url}
                  </a>
                </div>
              )}

              <div>
                <label className="text-white/50 text-sm">Image</label>
                {selectedArticle.image_url ? (
                  <div className="mt-2">
                    <img 
                      src={selectedArticle.image_url} 
                      alt="Article" 
                      className="w-full max-w-md rounded-lg"
                    />
                    {selectedArticle.image_credit && (
                      <p className="text-white/50 text-xs mt-2">
                        📸 {selectedArticle.image_photographer ? (
                          <a 
                            href={selectedArticle.image_credit_url} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="text-blue-400 hover:underline"
                          >
                            {selectedArticle.image_photographer}
                          </a>
                        ) : selectedArticle.image_credit}
                        {' on '}
                        <a 
                          href="https://unsplash.com" 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-blue-400 hover:underline"
                        >
                          Unsplash
                        </a>
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="text-white/40 text-sm">No image</p>
                )}
                <button
                  onClick={() => handleFetchImage(selectedArticle.id)}
                  disabled={fetchingImage}
                  className="mt-3 btn-secondary flex items-center gap-2"
                >
                  {fetchingImage ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      Fetching...
                    </>
                  ) : (
                    <>
                      <ImageIcon size={16} />
                      Fetch New Image
                    </>
                  )}
                </button>
              </div>
              
              {selectedArticle.approval_logs?.length > 0 && (
                <div>
                  <label className="text-white/50 text-sm">Approval History</label>
                  <div className="mt-2 space-y-2">
                    {selectedArticle.approval_logs.map((log) => (
                      <div key={log.id} className="bg-white/5 p-2 rounded text-sm">
                        <span className="text-white">{log.action}</span>
                        <span className="text-white/50 ml-2">by {log.moderator}</span>
                        <span className="text-white/30 ml-2">
                          {log.timestamp ? new Date(log.timestamp).toLocaleString() : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              <div className="flex gap-3 pt-4">
                <button 
                  onClick={() => { handleDeleteClick(selectedArticle); setSelectedArticle(null); }}
                  className="btn-danger flex items-center gap-2"
                >
                  <Trash2 size={16} />
                  Delete Article
                </button>
                <button 
                  onClick={() => setSelectedArticle(null)}
                  className="btn-secondary"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showDeleteModal && articleToDelete && (
        <div className="fixed inset-0 bg-black/85 flex items-center justify-center z-50 p-4">
          <div className="bg-white shadow-2xl border-2 border-gray-200 rounded-xl max-w-md w-full p-6">
            <div className="flex items-center gap-3 mb-4 text-red-600">
              <AlertTriangle size={24} />
              <h2 className="text-xl font-bold text-gray-900">Delete Article?</h2>
            </div>
            
            <div className="mb-4">
              <p className="text-gray-600 mb-2">You are about to delete:</p>
              <p className="text-gray-900 font-medium">{articleToDelete.title || 'Untitled'}</p>
              <p className="text-gray-500 text-sm">ID: {articleToDelete.id}</p>
            </div>
            
            <p className="text-red-600 font-bold mb-4">⚠️ This action cannot be undone!</p>
            
            <p className="text-gray-600 mb-4">
              Type <span className="text-red-600 font-mono font-bold">DELETE</span> to confirm:
            </p>
            
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="Type DELETE"
              className="w-full px-4 py-2 bg-gray-100 border-2 border-gray-300 rounded-lg text-gray-900 mb-4 focus:border-red-500 focus:outline-none"
            />
            
            <div className="flex gap-3">
              <button 
                onClick={handleDeleteConfirm}
                disabled={deleteConfirmText !== 'DELETE'}
                className="px-8 py-4 bg-red-600 hover:bg-red-700 disabled:bg-gray-400 text-white text-lg font-bold rounded-lg transition-colors shadow-lg flex-1"
              >
                🗑️ Delete Article
              </button>
              <button 
                onClick={() => { setShowDeleteModal(false); setArticleToDelete(null); }}
                className="px-6 py-4 bg-gray-200 hover:bg-gray-300 text-gray-800 font-medium rounded-lg transition-colors flex-1"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {showBulkDeleteModal && (
        <div className="fixed inset-0 bg-black/85 flex items-center justify-center z-50 p-4">
          <div className="bg-white shadow-2xl border-2 border-gray-200 rounded-xl max-w-md w-full p-6">
            <div className="flex items-center gap-3 mb-4 text-red-600">
              <AlertTriangle size={24} />
              <h2 className="text-xl font-bold text-gray-900">Delete {selectedIds.size} Articles?</h2>
            </div>
            
            <p className="text-red-600 font-bold mb-4">
              ⚠️ This action cannot be undone! All selected articles and their related data will be permanently deleted.
            </p>
            
            <p className="text-gray-600 mb-4">
              Type <span className="text-red-600 font-mono font-bold">DELETE</span> to confirm:
            </p>
            
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="Type DELETE"
              className="w-full px-4 py-2 bg-gray-100 border-2 border-gray-300 rounded-lg text-gray-900 mb-4 focus:border-red-500 focus:outline-none"
            />
            
            <div className="flex gap-3">
              <button 
                onClick={handleBulkDelete}
                disabled={deleteConfirmText !== 'DELETE'}
                className="px-8 py-4 bg-red-600 hover:bg-red-700 disabled:bg-gray-400 text-white text-lg font-bold rounded-lg transition-colors shadow-lg flex-1"
              >
                🗑️ Delete All
              </button>
              <button 
                onClick={() => { setShowBulkDeleteModal(false); setDeleteConfirmText(''); }}
                className="px-6 py-4 bg-gray-200 hover:bg-gray-300 text-gray-800 font-medium rounded-lg transition-colors flex-1"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ArticleManager
