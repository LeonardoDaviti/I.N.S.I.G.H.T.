# Testing Checklist - Database Posts Integration

## ✅ Pre-Flight Checks

### Backend Status
- [ ] PostgreSQL is running (`sudo systemctl status postgresql`)
- [ ] Database `insight` exists with tables created
- [ ] Backend API is running (`python backend/main.py`)
- [ ] Ingestion completed (272 posts exist for today)
- [ ] Endpoint test: `curl http://localhost:8000/api/posts/2025-10-30`

### Frontend Status
- [ ] Node modules installed (`npm install`)
- [ ] Frontend dev server running (`npm run dev`)
- [ ] No build errors in console
- [ ] Browser console shows no errors on page load

---

## 🎯 Core Feature Tests

### Test 1: Fetch Posts - Happy Path
**Steps:**
1. Open browser to `http://localhost:5173`
2. Ensure today's date is selected
3. Click **"Fetch Posts"** button

**Expected Results:**
- [ ] Button shows "⟳ Loading Posts..." with spinner
- [ ] After ~1-2 seconds, loading stops
- [ ] Green "Posts Loaded" badge appears in sidebar
- [ ] Badge shows: "📊 Total posts: 272" (or actual count)
- [ ] Badge shows: "📅 Date: 2025-10-30" (today)
- [ ] Badge shows: "💾 Source: database"
- [ ] Main content header changes to "📚 Database Posts (272)"
- [ ] Post cards render correctly
- [ ] All 272 posts are visible (scroll to verify)
- [ ] Browser console shows: `✅ Loaded 272 posts from database`

---

### Test 2: Post Card Interactions
**Steps:**
1. After fetching posts, find first post card
2. Click on the post card

**Expected Results:**
- [ ] Post expands to show full content
- [ ] Content is properly formatted (Markdown/HTML rendered)
- [ ] Post number badge shows "1"
- [ ] Platform label shows (e.g., "TELEGRAM", "RSS")
- [ ] Date displays correctly
- [ ] Source name displays (e.g., "ai_newz")

**Steps:**
3. Click 🔗 external link icon

**Expected Results:**
- [ ] Opens source URL in new tab
- [ ] URL is correct (matches post.url)

**Steps:**
4. Click 📋 copy icon

**Expected Results:**
- [ ] "Copied to clipboard" toast appears
- [ ] Toast disappears after 1.5 seconds
- [ ] Clipboard contains post text (paste in notepad to verify)

**Steps:**
5. Click 📤 share icon

**Expected Results:**
- [ ] "Copied to clipboard" toast appears
- [ ] Clipboard contains post URL (paste in notepad to verify)

---

### Test 3: Fetch Posts - Empty Result
**Steps:**
1. Select date: `2020-01-01` (date before any posts)
2. Click **"Fetch Posts"**

**Expected Results:**
- [ ] Button shows loading
- [ ] After load completes, no error shown
- [ ] Green "Posts Loaded" badge appears
- [ ] Badge shows: "📊 Total posts: 0"
- [ ] Main content shows: "No source posts available..."
- [ ] Browser console shows: `✅ Loaded 0 posts from database`

---

### Test 4: Fetch Posts - Invalid Date
**Steps:**
1. Manually type invalid date in input (if possible)
2. Or use browser dev tools to send invalid date format

**Expected Results:**
- [ ] Red error badge appears
- [ ] Error message mentions "Invalid date format"
- [ ] No posts displayed
- [ ] Browser console shows error

---

### Test 5: Network Error Handling
**Steps:**
1. Stop backend server
2. Click **"Fetch Posts"**

**Expected Results:**
- [ ] Button shows loading
- [ ] After timeout (~30s), shows error
- [ ] Red error badge appears
- [ ] Error message mentions "Network error" or "fetch failed"
- [ ] Browser console shows error details

---

### Test 6: Multiple Fetches
**Steps:**
1. Fetch posts for `2025-10-30`
2. Change date to `2025-10-29`
3. Click **"Fetch Posts"** again

**Expected Results:**
- [ ] Previous posts cleared before loading new ones
- [ ] New posts load successfully
- [ ] Badge updates with new date
- [ ] Post count updates
- [ ] No duplicate posts rendered

---

### Test 7: Switching Between Features
**Steps:**
1. Fetch database posts for today
2. Click **"Generate Briefing"** (AI briefing)
3. Wait for AI briefing to complete

**Expected Results:**
- [ ] AI briefing appears above posts section
- [ ] Posts section header changes back to "Source Intelligence Posts"
- [ ] Database posts replaced with AI-fetched posts
- [ ] Green briefing stats badge shows (not emerald)
- [ ] Emerald "Posts Loaded" badge disappears

**Steps:**
4. Click **"Fetch Posts"** again

**Expected Results:**
- [ ] AI briefing remains visible
- [ ] Posts section shows database posts again
- [ ] Header changes to "📚 Database Posts"
- [ ] Emerald badge reappears

---

## 🎨 UI/UX Tests

### Test 8: Visual Consistency
**Checks:**
- [ ] "Fetch Posts" button is emerald color (not indigo/purple)
- [ ] Button has same size/padding as other buttons
- [ ] Loading spinner rotates smoothly
- [ ] Badge colors match button colors (emerald for DB, green for AI)
- [ ] Post cards have consistent styling
- [ ] Icons are aligned properly
- [ ] Text is readable (no color contrast issues)

---

### Test 9: Responsive Design
**Desktop (1920x1080):**
- [ ] Sidebar visible at fixed width
- [ ] Main content centered, not too wide
- [ ] Post cards render properly
- [ ] Focus mode button works

**Tablet (768x1024):**
- [ ] Layout adjusts properly
- [ ] Buttons remain clickable
- [ ] Text remains readable

**Mobile (375x667):**
- [ ] Sidebar collapses (if implemented)
- [ ] Buttons stack vertically
- [ ] Post cards remain scrollable

---

### Test 10: Focus Mode
**Steps:**
1. Fetch database posts
2. Click focus mode button (eye icon)

**Expected Results:**
- [ ] Sidebar slides away
- [ ] Main content expands
- [ ] Posts remain visible and functional
- [ ] Focus button remains accessible
- [ ] Click again to restore sidebar

---

## 🔍 Edge Cases

### Test 11: Very Long Post Content
**Steps:**
1. Find post with very long content (>5000 chars)
2. Expand the post

**Expected Results:**
- [ ] Content renders without breaking layout
- [ ] Scrolling works properly
- [ ] No horizontal overflow
- [ ] Collapse still works

---

### Test 12: Posts with Special Characters
**Steps:**
1. Find post with emoji, Unicode, or special chars
2. Expand the post
3. Try copy function

**Expected Results:**
- [ ] Characters render correctly
- [ ] Copy preserves special characters
- [ ] No encoding issues

---

### Test 13: Posts with Media URLs
**Steps:**
1. Find post with media_urls field populated
2. Expand the post

**Expected Results:**
- [ ] Media links displayed (if implemented)
- [ ] Or gracefully ignored (no errors)
- [ ] Post remains functional

---

## 🐛 Known Issues to Test

### Test 14: Date Timezone Handling
**Steps:**
1. Fetch posts for today
2. Change system timezone
3. Refresh page and fetch again

**Expected Results:**
- [ ] Posts still load correctly
- [ ] Date display consistent
- [ ] No duplicate/missing posts

---

### Test 15: Concurrent Requests
**Steps:**
1. Click **"Fetch Posts"** button
2. Immediately click it again (before first completes)

**Expected Results:**
- [ ] Second click ignored (button disabled)
- [ ] Only one request sent
- [ ] No duplicate state updates
- [ ] No race conditions

---

## 📊 Performance Tests

### Test 16: Load Time
**Metrics to check:**
- [ ] API response time < 500ms (for 272 posts)
- [ ] Page render time < 1000ms
- [ ] Smooth scrolling through posts
- [ ] No lag when expanding/collapsing posts
- [ ] Memory usage reasonable (check browser dev tools)

---

### Test 17: Large Dataset
**Steps:**
1. Run ingestion script multiple times to create 1000+ posts
2. Fetch that date

**Expected Results:**
- [ ] All posts load (may take longer)
- [ ] UI remains responsive
- [ ] No browser freezing
- [ ] Consider pagination if > 1000 posts

---

## 🔐 Security Tests

### Test 18: XSS Protection
**Steps:**
1. Verify post content is sanitized
2. Check if HTML/scripts are escaped properly

**Expected Results:**
- [ ] No script execution from post content
- [ ] HTML rendered safely (MarkdownRenderer)
- [ ] No injection vulnerabilities

---

### Test 19: CORS
**Steps:**
1. Open browser dev tools → Network tab
2. Fetch posts
3. Check response headers

**Expected Results:**
- [ ] CORS headers present
- [ ] No CORS errors in console
- [ ] Request completes successfully

---

## ✅ Final Verification

### Test 20: Full End-to-End Flow
**Steps:**
1. Fresh browser tab (clear cache)
2. Navigate to app
3. Select today's date
4. Click **"Fetch Posts"**
5. Expand first post
6. Copy post content
7. Open external link
8. Switch to "Generate Briefing"
9. Return to "Fetch Posts"

**Expected Results:**
- [ ] No errors at any step
- [ ] All features work as expected
- [ ] UI remains consistent
- [ ] Data persists correctly
- [ ] Browser console clean (no errors/warnings)

---

## 📝 Test Results Log

| Test # | Feature | Status | Notes |
|--------|---------|--------|-------|
| 1 | Fetch Posts Happy Path | ⬜ | |
| 2 | Post Card Interactions | ⬜ | |
| 3 | Empty Result | ⬜ | |
| 4 | Invalid Date | ⬜ | |
| 5 | Network Error | ⬜ | |
| 6 | Multiple Fetches | ⬜ | |
| 7 | Feature Switching | ⬜ | |
| 8 | Visual Consistency | ⬜ | |
| 9 | Responsive Design | ⬜ | |
| 10 | Focus Mode | ⬜ | |
| 11 | Long Content | ⬜ | |
| 12 | Special Characters | ⬜ | |
| 13 | Media URLs | ⬜ | |
| 14 | Timezone Handling | ⬜ | |
| 15 | Concurrent Requests | ⬜ | |
| 16 | Load Time | ⬜ | |
| 17 | Large Dataset | ⬜ | |
| 18 | XSS Protection | ⬜ | |
| 19 | CORS | ⬜ | |
| 20 | E2E Flow | ⬜ | |

**Legend:** ⬜ Not Tested | ✅ Pass | ❌ Fail | ⚠️ Issue

---

## 🚀 Ready to Test!

**Before starting:**
1. Ensure backend is running on port 8000
2. Ensure frontend is running on port 5173
3. Ensure database has posts for today
4. Open browser dev tools (F12)
5. Keep this checklist handy

**Happy Testing! 🎉**


