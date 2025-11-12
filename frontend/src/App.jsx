import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom'
import { Home, MessageSquare, FileText, Users, BarChart } from 'lucide-react'
import HomePage from './pages/HomePage'
import ChatPage from './pages/ChatPage'
import ContentApproval from './pages/ContentApproval'

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-gray-50">
        <nav className="bg-purple-700 text-white shadow-lg">
          <div className="max-w-7xl mx-auto px-4">
            <div className="flex justify-between items-center h-16">
              <div className="flex items-center space-x-2">
                <BarChart className="h-8 w-8" />
                <h1 className="text-xl font-bold">Gradus Media AI Agent</h1>
              </div>
              <div className="flex space-x-6">
                <Link to="/" className="flex items-center space-x-1 hover:text-purple-200">
                  <Home size={20} />
                  <span>Home</span>
                </Link>
                <Link to="/chat" className="flex items-center space-x-1 hover:text-purple-200">
                  <MessageSquare size={20} />
                  <span>Chat</span>
                </Link>
                <Link to="/content" className="flex items-center space-x-1 hover:text-purple-200">
                  <FileText size={20} />
                  <span>Content Approval</span>
                </Link>
              </div>
            </div>
          </div>
        </nav>

        <main className="max-w-7xl mx-auto px-4 py-8">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/content" element={<ContentApproval />} />
          </Routes>
        </main>
      </div>
    </Router>
  )
}

export default App
