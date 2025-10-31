# Frontend UI Guide - Database Posts Feature

## Visual Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                          DAILY BRIEFING                              │
│                                                                      │
│  ┌─────────────────┐  ┌──────────────────────────────────────────┐ │
│  │   SIDEBAR       │  │         MAIN CONTENT AREA                 │ │
│  │                 │  │                                            │ │
│  │  Date: ________ │  │  ┌──────────────────────────────────┐    │ │
│  │                 │  │  │  📚 Database Posts (272)         │    │ │
│  │  [Generate      │  │  │                                  │    │ │
│  │   Briefing]     │  │  │  ┌────────────────────────────┐ │    │ │
│  │                 │  │  │  │ 1  [Post Title]            │ │    │ │
│  │  [Generate      │  │  │  │    📡 Source • 📅 Date     │ │    │ │
│  │   Topic-based]  │  │  │  │    Content preview...      │ │    │ │
│  │                 │  │  │  └────────────────────────────┘ │    │ │
│  │  [Fetch Posts]  │  │  │                                  │    │ │
│  │   ← NEW!        │  │  │  ┌────────────────────────────┐ │    │ │
│  │                 │  │  │  │ 2  [Post Title]            │ │    │ │
│  │  ┌───────────┐  │  │  │  │    📡 Source • 📅 Date     │ │    │ │
│  │  │ Posts     │  │  │  │  │    Content preview...      │ │    │ │
│  │  │ Loaded    │  │  │  │  └────────────────────────────┘ │    │ │
│  │  │ 📊 272    │  │  │  │                                  │    │ │
│  │  │ 📅 Date   │  │  │  │  ... (270 more posts)           │    │ │
│  │  │ 💾 DB     │  │  │  └──────────────────────────────────┘    │ │
│  │  └───────────┘  │  │                                            │ │
│  │                 │  │                                            │ │
│  └─────────────────┘  └──────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Button States

### Fetch Posts Button

#### **Idle State**
```
┌──────────────────────────────────────┐
│  📊  Fetch Posts                      │
└──────────────────────────────────────┘
Color: Emerald (bg-emerald-600)
```

#### **Loading State**
```
┌──────────────────────────────────────┐
│  ⟳  Loading Posts...                 │
└──────────────────────────────────────┘
Color: Emerald (bg-emerald-600)
Spinner: Rotating
Disabled: Yes
```

#### **After Success**
Button returns to idle, but sidebar shows:
```
┌──────────────────────────────────────┐
│  ✓  Posts Loaded                      │
│  📊 Total posts: 272                  │
│  📅 Date: 2025-10-26                  │
│  💾 Source: database                  │
└──────────────────────────────────────┘
Color: Emerald background (bg-emerald-50)
Border: emerald-200
```

---

## Color Coding System

| Element | Color | Meaning |
|---------|-------|---------|
| Generate Briefing | Indigo | AI processing (costs tokens) |
| Topic-based Briefing | Purple | AI clustering (costs tokens) |
| **Fetch Posts** | **Emerald** | **Database only (free, fast)** |
| Briefing Stats Badge | Green | AI briefing success |
| **Posts Loaded Badge** | **Emerald** | **Database fetch success** |
| Error Badge | Red | Something failed |

---

## User Interaction Flow

### Step-by-Step: Fetching Database Posts

1. **User Action:** Select date from date picker
   ```
   Date: [2025-10-26] ← User picks this
   ```

2. **User Action:** Click "Fetch Posts" button
   ```
   [Fetch Posts] ← Click
   ```

3. **System Response:** Button shows loading
   ```
   [⟳ Loading Posts...] ← Disabled, spinning
   ```

4. **System Response:** API call to backend
   ```
   GET /api/posts/2025-10-26
   ```

5. **System Response:** Success badge appears
   ```
   ┌─────────────────────────────┐
   │ ✓ Posts Loaded              │
   │ 📊 Total posts: 272         │
   │ 📅 Date: 2025-10-26         │
   │ 💾 Source: database         │
   └─────────────────────────────┘
   ```

6. **System Response:** Main area updates
   ```
   📚 Database Posts (272)
   
   [Post 1] ← Expandable
   [Post 2] ← Expandable
   [Post 3] ← Expandable
   ...
   ```

7. **User Can Now:**
   - Click any post to expand/collapse
   - Copy post content
   - Open source link
   - Share post link

---

## Post Card Interactions

### Collapsed State
```
┌────────────────────────────────────────────┐
│  1   [Post Title]              🔗 Copy 📤  │
│      📡 simonwillison • 📅 Oct 26          │
└────────────────────────────────────────────┘
```

### Expanded State
```
┌────────────────────────────────────────────┐
│  1   [Post Title]              🔗 Copy 📤  │
│      📡 simonwillison • 📅 Oct 26          │
│  ────────────────────────────────────────  │
│                                             │
│  [Full post content rendered here]         │
│  Supports Markdown, HTML, images, etc.     │
│                                             │
└────────────────────────────────────────────┘
```

### Actions on Each Post
- **🔗 External Link** - Opens source URL in new tab
- **📋 Copy** - Copies post text to clipboard
- **📤 Share** - Copies post URL to clipboard

---

## Error Handling

### Network Error
```
┌─────────────────────────────────┐
│ ⚠ Generation Failed             │
│ Network error occurred          │
└─────────────────────────────────┘
Color: Red (bg-red-50)
```

### Invalid Date Format
```
┌─────────────────────────────────┐
│ ⚠ Generation Failed             │
│ Invalid date format: 10-26-2025 │
│ Expected YYYY-MM-DD             │
└─────────────────────────────────┘
```

### No Posts Found (Not an error!)
```
📚 Database Posts (0)

┌─────────────────────────────────┐
│      📊                         │
│  No source posts available.     │
│  Generate a briefing to see     │
│  intelligence posts.            │
└─────────────────────────────────┘
```

---

## Responsive Behavior

### Desktop (> 768px)
- Sidebar: Fixed width (320px)
- Main content: Flexible, centered, max-width 4xl
- Focus mode: Hides sidebar, expands main content

### Tablet (768px - 1024px)
- Sidebar: Slightly narrower (280px)
- Main content: Full width with padding

### Mobile (< 768px)
- Sidebar: Hidden by default
- Main content: Full width
- Access sidebar via hamburger menu (if implemented)

---

## Accessibility Features

✅ **Keyboard Navigation**
- Tab through buttons
- Enter to activate
- Space to expand/collapse posts

✅ **Screen Reader Support**
- `aria-expanded` on post cards
- `aria-label` on icon buttons
- Proper heading hierarchy (h1 → h3)

✅ **Visual Indicators**
- Loading spinners
- Success badges
- Error messages
- Color + icon (not color alone)

---

## Performance Considerations

- **Lazy rendering:** Posts render as user scrolls (React virtual scrolling future enhancement)
- **Expand state:** Remembers which posts user expanded
- **Network caching:** Browser caches GET requests
- **Optimistic UI:** Shows loading immediately, no delay

---

## Future Enhancements (Not in Current Version)

- [ ] Search/filter posts by keyword
- [ ] Filter by platform (RSS, Telegram, etc.)
- [ ] Sort by date, relevance, length
- [ ] Bulk actions (select multiple, copy all)
- [ ] Export to JSON, CSV, Markdown
- [ ] Share entire day's posts via link
- [ ] Dark mode support
- [ ] Customizable post card layout

---

**Status:** ✅ All UI components implemented and ready for testing

**Last Updated:** October 30, 2025


