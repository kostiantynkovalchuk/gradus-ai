# Gradus Media AI Agent

Multi-stage AI agent system for automated content creation and approval workflow.

## Quick Start

### Frontend (Already Running)
The frontend is automatically running on port 5000. Access it through the Replit webview.

### Backend
Start the backend API server:
```bash
cd backend && python start.py
```

Or manually:
```bash
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000` with interactive docs at `/docs`.

## Testing

### Test Claude Chat
1. Go to the **Chat** page in the dashboard
2. Enter a message and click "Send Message"
3. Try the translation feature with English text

### Test Content Approval
1. Content will appear on the **Content Approval** page when scraped
2. Review, approve, or reject content
3. Edit translations or regenerate images before approval

## Environment Setup

Required environment variables (set in Replit Secrets):
- `ANTHROPIC_API_KEY` - For Claude AI (chat & translation)
- `DATABASE_URL` - PostgreSQL connection (auto-configured)

Optional:
- `OPENAI_API_KEY` - For DALL-E image generation
- `PINECONE_API_KEY` - For RAG functionality

## API Endpoints

- `GET /` - API info
- `GET /health` - Health check
- `POST /chat` - Chat with Claude
- `POST /translate` - Translate English → Ukrainian
- `GET /api/content/pending` - Get pending content
- `POST /api/content/{id}/approve` - Approve content
- `POST /api/content/{id}/reject` - Reject content
- `PUT /api/content/{id}/edit` - Edit content
- `GET /api/content/stats` - Get statistics

## Project Structure

```
├── backend/              # FastAPI application
│   ├── main.py          # API endpoints
│   ├── models/          # Database models
│   └── services/        # Business logic
├── frontend/            # React dashboard
│   └── src/
│       ├── pages/       # Dashboard pages
│       └── App.jsx      # Main app
└── replit.md           # Detailed documentation
```

See `replit.md` for complete documentation.
