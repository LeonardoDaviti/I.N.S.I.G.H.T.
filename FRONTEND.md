# Frontend Development Guide

## Architecture Overview

The INSIGHT frontend is a React + TypeScript application using:
- **React** - Component library
- **TypeScript** - Type safety
- **Tailwind CSS** - Styling
- **Vite** - Build tool
- **Lucide React** - Icons

```
frontend/
├── src/
│   ├── pages/           # Full page components
│   ├── components/      # Reusable UI components
│   ├── services/        # API communication
│   ├── types/           # TypeScript type definitions
│   └── lib/             # Utility functions
```

---

## Part 1: Integrating Backend Features

### Step-by-Step Process

#### 1. **Define TypeScript Types** (`src/services/api.ts`)

First, define the data structure you'll receive from the backend:

```typescript
// Define the response interface
export interface PostsBySourceResponse {
  success: boolean;
  posts: Post[];
  source_id: string;
  total: number;
  error?: string;
}

// Post interface (if not already defined)
export interface Post {
  id?: string;
  title?: string;
  content: string;
  content_html?: string;
  date?: string | null;
  source: string;
  platform: string;
  url?: string;
  feed_title?: string;
  media_urls?: string[];
}
```

---

#### 2. **Create API Service Method** (`src/services/api.ts`)

Add a method to the `ApiService` class:

```typescript
class ApiService {
  // ... existing methods ...
  
  async getPostsBySource(sourceId: string): Promise<PostsBySourceResponse> {
    try {
      const response = await this.makeRequest<PostsBySourceResponse>(
        `/api/posts/source/${sourceId}`
      );
      return response;
    } catch (error) {
      console.error('Failed to get posts by source:', error);
      return {
        success: false,
        posts: [],
        source_id: sourceId,
        total: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }
}
```

**Pattern:**
- Use `this.makeRequest<ResponseType>()` for API calls
- Always handle errors and return a valid response structure
- Log errors to console for debugging

---

#### 3. **Import Types in Components**

At the top of your page component:

```typescript
import { apiService } from '../services/api';
import type { PostsBySourceResponse, Post } from '../services/api';
```

---

#### 4. **Create State Management**

Use React hooks to manage data:

```typescript
export default function YourPage() {
  // State for posts data
  const [posts, setPosts] = useState<Post[]>([]);
  
  // State for loading indicator
  const [isLoading, setIsLoading] = useState(false);
  
  // State for error handling
  const [error, setError] = useState<string | null>(null);
  
  // State for metadata
  const [stats, setStats] = useState<{
    total: number;
    source_id: string;
  } | null>(null);
  
  // ... rest of component
}
```

---

#### 5. **Create Handler Function**

Create an async function to fetch data:

```typescript
const handleLoadPostsBySource = async (sourceId: string) => {
  setIsLoading(true);
  setError(null);
  setPosts([]);
  setStats(null);
  
  try {
    console.log(`📖 Loading posts for source: ${sourceId}`);
    const response = await apiService.getPostsBySource(sourceId);
    
    if (response.success) {
      console.log(`✅ Loaded ${response.total} posts`);
      setPosts(response.posts);
      setStats({
        total: response.total,
        source_id: response.source_id
      });
    } else {
      console.error('❌ Failed to load posts:', response.error);
      setError(response.error || 'Failed to load posts');
    }
  } catch (error) {
    console.error('❌ API call failed:', error);
    setError(error instanceof Error ? error.message : 'Network error occurred');
  } finally {
    setIsLoading(false);
  }
};
```

**Pattern:**
- Always set loading state before and after
- Clear previous data before fetching
- Handle both success and error cases
- Add console logging for debugging
- Use try/catch/finally

---

#### 6. **Call Handler Function**

Trigger the handler from UI events:

```typescript
// From a button click
<button onClick={() => handleLoadPostsBySource(sourceId)}>
  Load Posts
</button>

// From a dropdown/select change
<select onChange={(e) => handleLoadPostsBySource(e.target.value)}>
  {sources.map(source => (
    <option key={source.id} value={source.id}>
      {source.name}
    </option>
  ))}
</select>

// On component mount
useEffect(() => {
  handleLoadPostsBySource(defaultSourceId);
}, []);

// When a dependency changes
useEffect(() => {
  if (selectedSourceId) {
    handleLoadPostsBySource(selectedSourceId);
  }
}, [selectedSourceId]);
```

---

#### 7. **Display Data in UI**

Render the data with conditional logic:

```typescript
return (
  <div>
    {/* Loading State */}
    {isLoading && (
      <div className="text-center py-8">
        <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-2" />
        <p>Loading posts...</p>
      </div>
    )}
    
    {/* Error State */}
    {error && (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <AlertCircle className="w-4 h-4 text-red-600" />
        <span className="text-red-800">{error}</span>
      </div>
    )}
    
    {/* Success State */}
    {posts.length > 0 && (
      <div className="space-y-4">
        <h2>Found {stats?.total} posts</h2>
        {posts.map((post, index) => (
          <div key={post.id || index} className="border rounded-lg p-4">
            <h3>{post.title}</h3>
            <p>{post.content}</p>
          </div>
        ))}
      </div>
    )}
    
    {/* Empty State */}
    {!isLoading && !error && posts.length === 0 && (
      <div className="text-center py-8 text-gray-500">
        <p>No posts found</p>
      </div>
    )}
  </div>
);
```

---

## Part 2: Updating Cosmetics & Design

### Tailwind CSS Class Reference

#### Layout & Spacing
```css
p-4          /* padding: 1rem (16px) */
px-4         /* padding-left + padding-right */
py-4         /* padding-top + padding-bottom */
m-4          /* margin: 1rem */
space-y-4    /* vertical spacing between children */
gap-4        /* gap in flex/grid layouts */
```

#### Sizing
```css
w-full       /* width: 100% */
w-80         /* width: 20rem (320px) */
h-screen     /* height: 100vh */
max-w-4xl    /* max-width: 56rem (896px) */
```

#### Typography
```css
text-sm      /* font-size: 0.875rem (14px) */
text-base    /* font-size: 1rem (16px) */
text-lg      /* font-size: 1.125rem (18px) */
text-xl      /* font-size: 1.25rem (20px) */
text-2xl     /* font-size: 1.5rem (24px) */
text-3xl     /* font-size: 1.875rem (30px) */

font-medium  /* font-weight: 500 */
font-semibold /* font-weight: 600 */
font-bold    /* font-weight: 700 */
```

#### Colors
```css
text-gray-600    /* text color */
bg-blue-50       /* background color (light) */
bg-blue-600      /* background color (dark) */
border-gray-200  /* border color */
```

---

### How to Resize Everything by 10%

**Method 1: Reduce Tailwind Class Sizes**

Replace all spacing/typography classes with smaller equivalents:
```typescript
// Before
<div className="p-8 text-3xl">

// After (10% reduction)
<div className="p-7 text-2xl">
```

**Mapping Guide:**
- `p-8` → `p-7` (32px → 28px)
- `p-6` → `p-5` (24px → 20px)
- `p-4` → `p-3.5` (16px → 14px)
- `text-3xl` → `text-2xl` (30px → 24px)
- `text-xl` → `text-lg` (20px → 18px)
- `w-80` → `w-72` (320px → 288px)

**Method 2: Global CSS Scale (Quick but affects everything)**

In `src/index.css`:
```css
#root {
  transform: scale(0.9);
  transform-origin: top left;
  width: 111.11%; /* compensate for scale */
  height: 111.11%;
}
```

---

### Common Design Patterns

#### Card Component
```typescript
<div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
  <h3 className="text-lg font-semibold mb-4">Card Title</h3>
  <p className="text-gray-600">Card content</p>
</div>
```

#### Button Styles
```typescript
// Primary Button
<button className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
  Click Me
</button>

// Secondary Button
<button className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors">
  Cancel
</button>

// Disabled Button
<button 
  disabled={isLoading}
  className="px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
>
  Submit
</button>
```

#### Loading Spinner
```typescript
import { RefreshCw } from 'lucide-react';

<RefreshCw className="w-4 h-4 animate-spin" />
```

---

### Removing/Hiding Elements

**Method 1: Conditional Rendering (Removes from DOM)**
```typescript
{shouldShow && <div>Content</div>}
```

**Method 2: CSS Hidden (Keeps in DOM)**
```typescript
<div className="hidden">Content</div>
```

**Method 3: Opacity (Keeps space)**
```typescript
<div className="opacity-0">Content</div>
```

---

### Sidebar Navigation Pattern

```typescript
const sections = [
  { id: 'all', title: 'All Posts', count: 321 },
  { id: 'source-1', title: 'Source 1', count: 23 },
  { id: 'source-2', title: 'Source 2', count: 13 },
];

const [activeSection, setActiveSection] = useState('all');

return (
  <div className="flex h-screen">
    {/* Sidebar */}
    <div className="w-80 bg-white border-r">
      <nav className="space-y-1 p-4">
        {sections.map((section) => (
          <button
            key={section.id}
            onClick={() => setActiveSection(section.id)}
            className={`w-full flex items-center justify-between px-3 py-2 rounded-lg ${
              activeSection === section.id
                ? 'bg-blue-50 text-blue-900'
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <span>{section.title}</span>
            <span className="text-sm text-gray-500">{section.count}</span>
          </button>
        ))}
      </nav>
    </div>
    
    {/* Main Content */}
    <div className="flex-1 overflow-y-auto p-8">
      {/* Content for active section */}
    </div>
  </div>
);
```

---

## Debugging Tips

1. **Check API Response in Browser DevTools:**
   - Open Network tab
   - Find the API request
   - Check response status and body

2. **Console Logging:**
   ```typescript
   console.log('Data:', data);
   console.error('Error:', error);
   console.table(array); // Pretty print arrays
   ```

3. **React DevTools:**
   - Install React DevTools browser extension
   - Inspect component state and props

4. **Type Checking:**
   ```bash
   cd frontend
   npm run type-check  # If available
   ```

---

## Auto-fetch on Date Change

```typescript
const [selectedDate, setSelectedDate] = useState(
  new Date().toISOString().split('T')[0]
);

// Auto-fetch when date changes
useEffect(() => {
  handleLoadPosts(selectedDate);
}, [selectedDate]);

return (
  <input
    type="date"
    value={selectedDate}
    onChange={(e) => setSelectedDate(e.target.value)}
  />
);
```

This automatically calls `handleLoadPosts` whenever the date changes - no button needed!

