# INTEGRATION_INSTRUCTIONS.md - Exact steps to add chat to your existing system

## 🎯 What You're Adding

NEW chat system with Maya & Alex avatars that works ALONGSIDE your existing:
- Content scraping
- Translation
- Image generation
- Telegram approvals
- Facebook posting

## 📁 Step 1: Add New Files

Add these 3 NEW files to your project (don't change existing files yet):

```
your-project/
├── avatar_personalities.py    # NEW - Download from outputs
├── chat_endpoints.py           # NEW - Download from outputs
└── rag_utils.py               # NEW - Download from outputs
```

## 📝 Step 2: Minimal Changes to main.py

Open your existing `main.py` and add ONLY these lines:

### At the top (with your imports):

```python
# Your existing imports stay here:
# from fastapi import FastAPI
# from anthropic import Anthropic
# etc...

# ADD THIS NEW IMPORT (just this one line):
from chat_endpoints import chat_router
```

### After app = FastAPI():

```python
# Your existing code:
app = FastAPI(title="Gradus AI Backend")

# ADD THIS ONE LINE:
app.include_router(chat_router)

# Rest of your existing code stays the same
```

**That's it!** Just 2 lines added to main.py.

## 📦 Step 3: Update requirements.txt

Open your existing `requirements.txt` and ADD these lines (don't remove existing ones):

```txt
# Your existing dependencies stay here
# fastapi==...
# anthropic==...
# sqlalchemy==...
# etc.

# ADD these 4 new packages:
pinecone-client==3.0.0
sentence-transformers==2.2.2
langchain==0.1.0
langchain-community==0.0.10
```

## 🔑 Step 4: Add Pinecone API Keys to Render

1. Go to [app.pinecone.io](https://app.pinecone.io) (if you don't have an account)
2. OR use your existing Pinecone account (you already have one!)
3. In Render dashboard:
   - Your Service → Environment
   - Add: `PINECONE_API_KEY` = `[copy from Replit Secrets]`
   - Add: `PINECONE_INDEX_NAME` = `gradus-media`
   - Click Save (will trigger redeploy)

**Important:** Make sure to copy the exact same values from Replit to Render!

## 🚀 Step 5: Deploy

```bash
# If using Git
git add avatar_personalities.py chat_endpoints.py rag_utils.py main.py requirements.txt
git commit -m "Add chat system with avatars"
git push origin main

# Render will auto-deploy
```

## ✅ Step 6: Test Everything Still Works

### Test existing system:
```bash
# Your existing endpoints should still work
curl https://gradus-ai.onrender.com/health
curl https://gradus-ai.onrender.com/status
curl https://gradus-ai.onrender.com/api/articles
```

### Test new chat endpoints:
```bash
# List avatars
curl https://gradus-ai.onrender.com/chat/avatars

# Chat with Maya
curl -X POST https://gradus-ai.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Які тренди в горілці?", "avatar": "maya"}'

# Ingest website
curl -X POST https://gradus-ai.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Вивчи https://avtd.com"}'
```

## 📊 Verify Both Systems Work

After deployment, you should see:

**Existing system (unchanged):**
- ✅ Scraping runs every 6 hours
- ✅ Articles get translated
- ✅ Images generated with DALL-E
- ✅ Telegram approvals work
- ✅ Facebook posts go out
- ✅ Database has your 106 articles

**New chat system (added):**
- 🆕 `/chat` endpoint works
- 🆕 `/chat/avatars` lists Maya/Alex/General
- 🆕 Can ingest websites
- 🆕 Can answer questions using RAG
- 🆕 3 distinct avatar personalities

## 🔄 What Changed?

### Your main.py before:
```python
from fastapi import FastAPI
# ... other imports ...

app = FastAPI(title="Gradus AI Backend")

# Your existing endpoints:
@app.get("/health")
@app.get("/status")
@app.post("/approve-article")
# etc...
```

### Your main.py after:
```python
from fastapi import FastAPI
# ... other imports ...
from chat_endpoints import chat_router  # NEW LINE

app = FastAPI(title="Gradus AI Backend")
app.include_router(chat_router)  # NEW LINE

# Your existing endpoints (unchanged):
@app.get("/health")
@app.get("/status")
@app.post("/approve-article")
# etc...
```

## 🎯 New Endpoints Available

After integration:

```
POST   /chat                    - Chat with avatars (Maya/Alex/General)
GET    /chat/avatars            - List available avatars
POST   /chat/switch-avatar      - Switch to specific avatar
GET    /chat/knowledge-stats    - Vector database statistics
DELETE /chat/clear-knowledge    - Clear knowledge base
GET    /chat/health             - Chat system health check
```

All your existing endpoints keep working!

## 🐛 Troubleshooting

### "ModuleNotFoundError: No module named 'chat_endpoints'"
- Make sure you added `chat_endpoints.py` to your project
- Redeploy to Render

### "ModuleNotFoundError: No module named 'sentence_transformers'"
- Make sure you updated `requirements.txt`
- Render will install on deploy

### "PINECONE_API_KEY not found"
- Add it in Render Dashboard → Environment
- Save (triggers redeploy)

### Existing endpoints stop working
- Check Render logs for errors
- Rollback: remove the 2 lines from main.py
- Commit and push

## 🔙 Rollback if Needed

If anything breaks:

```bash
# Remove the 2 lines from main.py:
# - from chat_endpoints import chat_router
# - app.include_router(chat_router)

# Remove the 4 packages from requirements.txt

# Commit and push
git add main.py requirements.txt
git commit -m "Rollback chat system"
git push origin main
```

## 🎉 Success!

You now have:
- ✅ Working content pipeline (untouched)
- ✅ New chat system with 3 avatars
- ✅ RAG capabilities
- ✅ Website ingestion
- ✅ Both systems independent

**Total changes to existing code: 2 lines in main.py!**
