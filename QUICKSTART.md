# 🚀 Quick Start Guide - Database Posts Feature

## Step 1: Start Backend (Terminal 1)

```bash
cd /home/man/Documents/I.N.S.I.G.H.T.
python backend/main.py
```

**Expected output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## Step 2: Start Frontend (Terminal 2)

```bash
cd /home/man/Documents/I.N.S.I.G.H.T./frontend
npm run dev
```

**Expected output:**
```
  VITE v5.x.x  ready in xxx ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

---

## Step 3: Open Browser

Navigate to: **http://localhost:5173**

You should see the Daily Briefing page with three buttons:
- **Generate Briefing** (Indigo)
- **Generate Topic-based Briefing** (Purple)
- **Fetch Posts** (Emerald) ← **NEW!**

---

## Step 4: Test the Feature

1. **Select today's date** (should be pre-selected)
2. **Click "Fetch Posts"** button
3. **Wait ~1 second**
4. **See results:**
   - Green badge appears: "Posts Loaded"
   - Shows: "📊 Total posts: 272"
   - Main content shows: "📚 Database Posts (272)"
   - All posts rendered in cards

---

## Step 5: Interact with Posts

### Expand a Post
- Click any post card
- Content expands to show full text
- Markdown/HTML rendered properly

### Copy Post Content
- Click 📋 (copy icon) on any post
- Toast message: "Copied to clipboard"
- Paste in notepad to verify

### Open Source Link
- Click 🔗 (link icon) on any post
- Opens source URL in new tab

### Share Post
- Click 📤 (share icon) on any post
- Copies post URL to clipboard

---

## Troubleshooting

### "Network error occurred"
**Problem:** Backend not running  
**Solution:** Start backend (Step 1)

### "No posts available"
**Problem:** Database empty  
**Solution:** Run ingestion script:
```bash
cd /home/man/Documents/I.N.S.I.G.H.T.
python backend/insight_core/scripts/ingest.py
```

### "Invalid date format"
**Problem:** Date format incorrect  
**Solution:** Use YYYY-MM-DD format (e.g., 2025-10-30)

### Frontend won't start
**Problem:** Dependencies not installed  
**Solution:**
```bash
cd frontend
npm install
npm run dev
```

### Backend error: "Database does not exist"
**Problem:** PostgreSQL not set up  
**Solution:**
```bash
cd /home/man/Documents/I.N.S.I.G.H.T./backend/insight_core/db
python ensure_db.py
python migrate.py
python seed_sources.py
```

---

## Quick Verification

### Test Backend Directly
```bash
curl "http://localhost:8000/api/posts/2025-10-30"
```

**Expected:** JSON with posts array

### Check Database
```bash
psql -U insight -d insight -c "SELECT COUNT(*) FROM posts WHERE DATE(COALESCE(published_at, fetched_at)) = '2025-10-30';"
```

**Expected:** Number like `272`

---

## Success Criteria

✅ Backend running on port 8000  
✅ Frontend running on port 5173  
✅ "Fetch Posts" button visible  
✅ Button changes to "Loading Posts..." when clicked  
✅ Emerald badge appears after loading  
✅ Posts display in cards  
✅ Posts are expandable  
✅ Copy/share buttons work  

---

## What to Test

1. ✅ Fetch posts for today (should have data)
2. ✅ Fetch posts for old date (should show 0 posts, no error)
3. ✅ Expand/collapse posts
4. ✅ Copy post content
5. ✅ Open external links
6. ✅ Switch between "Fetch Posts" and "Generate Briefing"

---

## Next Steps

Once basic functionality works:
1. Review `TESTING_CHECKLIST.md` for comprehensive tests
2. Check `FRONTEND_UI_GUIDE.md` for UI details
3. Read `DATABASE_POSTS_COMPLETE.md` for architecture overview

---

## Need Help?

- Check browser console (F12) for errors
- Check backend logs in terminal
- Review error messages in red badges
- Verify database has posts: `SELECT COUNT(*) FROM posts;`

---

**Ready? Let's go! 🚀**

1. Start backend
2. Start frontend  
3. Open browser
4. Click "Fetch Posts"
5. Celebrate! 🎉


