import { BarChart, MessageSquare, FileText, Users, TrendingUp } from 'lucide-react'
import { Link } from 'react-router-dom'

function HomePage() {
  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Welcome to Gradus Media AI Agent</h1>
        <p className="text-gray-600">Automated content creation and approval system for social media</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        <div className="bg-white p-6 rounded-lg shadow">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Pending Approval</h3>
            <FileText className="text-purple-600" size={24} />
          </div>
          <p className="text-3xl font-bold text-purple-600">0</p>
          <p className="text-sm text-gray-500 mt-2">Content awaiting review</p>
        </div>

        <div className="bg-white p-6 rounded-lg shadow">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Approved</h3>
            <TrendingUp className="text-green-600" size={24} />
          </div>
          <p className="text-3xl font-bold text-green-600">0</p>
          <p className="text-sm text-gray-500 mt-2">Ready to post</p>
        </div>

        <div className="bg-white p-6 rounded-lg shadow">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Posted</h3>
            <Users className="text-blue-600" size={24} />
          </div>
          <p className="text-3xl font-bold text-blue-600">0</p>
          <p className="text-sm text-gray-500 mt-2">Published content</p>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold mb-4">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Link 
            to="/chat"
            className="flex items-center space-x-3 p-4 border border-gray-200 rounded-lg hover:bg-purple-50 hover:border-purple-300 transition"
          >
            <MessageSquare className="text-purple-600" size={24} />
            <div>
              <h3 className="font-semibold">Test Claude Chat</h3>
              <p className="text-sm text-gray-500">Chat with Claude AI and test translation</p>
            </div>
          </Link>

          <Link 
            to="/content"
            className="flex items-center space-x-3 p-4 border border-gray-200 rounded-lg hover:bg-purple-50 hover:border-purple-300 transition"
          >
            <FileText className="text-purple-600" size={24} />
            <div>
              <h3 className="font-semibold">Review Content</h3>
              <p className="text-sm text-gray-500">Approve or reject pending content</p>
            </div>
          </Link>
        </div>
      </div>

      <div className="mt-8 bg-blue-50 border border-blue-200 rounded-lg p-6">
        <h3 className="text-lg font-semibold text-blue-900 mb-2">System Status</h3>
        <ul className="space-y-2 text-sm text-blue-800">
          <li>✅ FastAPI Backend: Running</li>
          <li>✅ Claude API: Configured</li>
          <li>✅ PostgreSQL Database: Connected</li>
          <li>⏳ DALL-E Image Generation: Awaiting API key</li>
          <li>⏳ Social Media Posting: Awaiting credentials</li>
        </ul>
      </div>
    </div>
  )
}

export default HomePage
