# 🎯 YOUR INTEGRATION CHECKLIST - Ready to Go!

## ✅ What You Already Have

- ✅ PINECONE_API_KEY in Replit Secrets
- ✅ PINECONE_INDEX_NAME = `gradus-media` in Replit Secrets
- ✅ Working content pipeline (scraping, translation, posting)
- ✅ Files downloaded and ready to use

**You're 90% ready!** Just need to integrate the files.

---

## 📋 Step-by-Step Integration (15 minutes)

### **Step 1: Add Files to Replit** ⏱️ 2 min

Download these 3 files from outputs and add to your Replit project:

```
your-replit-project/
├── main.py                    # YOUR EXISTING FILE
├── avatar_personalities.py    # NEW - Download from outputs
├── chat_endpoints.py          # NEW - Download from outputs (updated for gradus-media)
└── rag_utils.py              # NEW - Download from outputs
```

**How to add:**
1. In Replit, click **+** (Add file) 
2. Upload or create each file
3. Copy-paste content from downloaded files

---

### **Step 2: Update main.py** ⏱️ 1 min

Open your existing `main.py` and add **just 2 lines**:

#### At the top (with imports):
```python
# Your existing imports:
# from fastapi import FastAPI
# from anthropic import Anthropic
# ... etc ...

# ADD THIS ONE LINE:
from chat_endpoints import chat_router
```

#### After `app = FastAPI()`:
```python
# Your existing code:
app = FastAPI(title="Gradus AI Backend")

# ADD THIS ONE LINE:
app.include_router(chat_router)

# Rest of your code stays the same
```

**That's it! Only 2 lines added.**

---

### **Step 3: Update requirements.txt** ⏱️ 1 min

Open your `requirements.txt` and **add** these 4 lines at the end:

```txt
# Your existing packages stay here
# ...

# ADD these 4 new packages:
pinecone-client==3.0.0
sentence-transformers==2.2.2
langchain==0.1.0
langchain-community==0.0.10
```

---

### **Step 4: Test in Replit** ⏱️ 3 min

```bash
# Run your app
python main.py

# Should see:
# ✅ Uvicorn running on http://...
# ✅ No import errors
```

**If you see errors:**
- "ModuleNotFoundError" → Install packages: `pip install -r requirements.txt`
- "cannot import chat_endpoints" → Make sure file is in project root

---

### **Step 5: Test Chat Endpoints** ⏱️ 2 min

Open a new terminal in Replit or use curl:

```bash
# List avatars
curl http://localhost:8000/chat/avatars

# Expected response:
# {"avatars": ["maya", "alex", "general"], ...}

# Test Maya
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Які тренди в горілці?", "avatar": "maya"}'

# Should get Maya's response about vodka trends
```

**If chat works in Replit → Ready for Render!**

---

### **Step 6: Add to Render Environment** ⏱️ 2 min

1. Go to [dashboard.render.com](https://dashboard.render.com)
2. Select your `gradus-ai` service
3. Click **Environment** tab
4. Add these 2 variables (copy from Replit):

```
PINECONE_API_KEY = [click eye icon in Replit Secrets, copy value]
PINECONE_INDEX_NAME = gradus-media
```

5. Click **Save Changes** (will trigger auto-redeploy)

---

### **Step 7: Deploy to Render** ⏱️ 3 min

```bash
# In Replit terminal or your local git:
git add avatar_personalities.py chat_endpoints.py rag_utils.py main.py requirements.txt
git commit -m "Add chat system with Maya & Alex avatars"
git push origin main
```

**Render will:**
1. Detect changes
2. Install new packages
3. Redeploy automatically
4. Takes ~2-3 minutes

Watch the logs in Render dashboard:
- ✅ "Build succeeded"
- ✅ "Deploy succeeded"
- ✅ "Service is live"

---

### **Step 8: Test Production** ⏱️ 1 min

```bash
# Test existing system still works
curl https://gradus-ai.onrender.com/health
curl https://gradus-ai.onrender.com/status

# Test new chat system
curl https://gradus-ai.onrender.com/chat/avatars

# Test Maya chat
curl -X POST https://gradus-ai.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Які тренди в крафтовій горілці?", "avatar": "maya"}'
```

**Expected:**
- ✅ All old endpoints work
- ✅ New chat endpoints work
- ✅ Maya responds with personality
- ✅ Content scraping still running

---

## 🎉 Success Criteria

You're done when:

```
✅ Replit runs without errors
✅ /chat/avatars returns 3 avatars
✅ Maya chat works with personality
✅ Alex chat works with personality
✅ Render deploys successfully
✅ Production endpoints work
✅ Old system (scraping/posting) still works
✅ New chat system works alongside
```

---

## 🐛 Quick Troubleshooting

### "ModuleNotFoundError: sentence_transformers"
**Fix:** In Replit, run:
```bash
pip install sentence-transformers==2.2.2
```

### "cannot import name 'chat_router'"
**Fix:** Make sure `chat_endpoints.py` is in the same directory as `main.py`

### "PINECONE_API_KEY not found" (in Render)
**Fix:** 
1. Check Render Dashboard → Environment
2. Add `PINECONE_API_KEY` and `PINECONE_INDEX_NAME`
3. Save (triggers redeploy)

### Old endpoints stop working
**Fix:**
1. Check Render logs for errors
2. If needed, rollback: remove 2 lines from main.py
3. Commit and push

---

## 📊 Your System After Integration

### Existing System (Untouched):
```
✅ Scraping 6 sources every 6 hours
✅ Translation with Claude API
✅ DALL-E image generation
✅ Telegram approval workflow
✅ Facebook posting
✅ 106 articles in PostgreSQL
✅ APScheduler automation
```

### New Chat System (Added):
```
🆕 POST /chat - Maya/Alex/General avatars
🆕 GET /chat/avatars - List avatars
🆕 GET /chat/knowledge-stats - Vector DB stats
🆕 Website ingestion via chat
🆕 RAG from learned content
🆕 Pinecone index: gradus-media
```

---

## 🎯 Next Steps After Integration

Once working:

1. **Test avatars:**
   - Ask Maya marketing questions
   - Ask Alex cocktail questions
   - Test auto-detection

2. **Ingest AVTD website:**
   ```bash
   curl -X POST https://gradus-ai.onrender.com/chat \
     -d '{"message": "Вивчи https://avtd.com"}'
   ```

3. **Test knowledge retrieval:**
   ```bash
   curl -X POST https://gradus-ai.onrender.com/chat \
     -d '{"message": "Які бренди є в AVTD?"}'
   ```

4. **Ready for Stage 2!**
   - Maya can now do FB outreach
   - Has knowledge of AVTD products
   - Can answer customer questions

---

## 💾 Backup Plan

Before starting, backup your current working system:

```bash
cp main.py main.py.backup
cp requirements.txt requirements.txt.backup
git commit -m "Backup before chat integration"
```

If anything breaks:
```bash
# Restore from backup
cp main.py.backup main.py
cp requirements.txt.backup requirements.txt

# Or git revert
git revert HEAD

# Push and Render redeploys to previous version
git push origin main
```

---

## ⏱️ Total Time: ~15 minutes

- Step 1: 2 min (add files)
- Step 2: 1 min (update main.py)
- Step 3: 1 min (update requirements.txt)
- Step 4: 3 min (test in Replit)
- Step 5: 2 min (test endpoints)
- Step 6: 2 min (add to Render)
- Step 7: 3 min (deploy)
- Step 8: 1 min (test production)

**Ready to start? Begin with Step 1!** 🚀
