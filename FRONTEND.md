# Frontend Development Guide

## Architecture Overview

The INSIGHT frontend is built with React, TypeScript, and Tailwind CSS:

```
┌──────────────────────────────────────┐
│   Pages (pages/)                     │  Main app views
├──────────────────────────────────────┤
│   Components (components/)           │  Reusable UI elements
├──────────────────────────────────────┤
│   Services (services/api.ts)         │  API communication
├──────────────────────────────────────┤
│   Types (types/)                     │  TypeScript definitions
└──────────────────────────────────────┘
```

## How to Implement Frontend Features

### Step 1: Add TypeScript Types

Define interfaces in `frontend/src/services/api.ts`:

```typescript
export interface NewFeature {
  id: string;
  name: string;
  value: number;
}

export interface NewFeatureResponse {
  success: boolean;
  data: NewFeature[];
  error?: string;
}
```

### Step 2: Add API Methods

Add service methods in `frontend/src/services/api.ts`:

```typescript
class ApiService {
  async getNewFeature(id: string): Promise<NewFeatureResponse> {
    try {
      const response = await this.makeRequest<NewFeatureResponse>(`/api/new-feature/${id}`);
      return response;
    } catch (error) {
      console.error('Failed to get new feature:', error);
      return {
        success: false,
        data: [],
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async updateNewFeature(id: string, data: Partial<NewFeature>): Promise<NewFeatureResponse> {
    try {
      const response = await this.makeRequest<NewFeatureResponse>(`/api/new-feature/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      });
      return response;
    } catch (error) {
      console.error('Failed to update new feature:', error);
      return {
        success: false,
        data: [],
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }
}
```

### Step 3: Use in Components

```typescript
import { apiService } from '../services/api';
import type { NewFeature } from '../services/api';

export default function MyComponent() {
  const [data, setData] = useState<NewFeature[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await apiService.getNewFeature('123');

      if (response.success) {
        setData(response.data);
      } else {
        setError(response.error || 'Failed to load data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error}</div>;

  return (
    <div>
      {data.map(item => (
        <div key={item.id}>{item.name}</div>
      ))}
    </div>
  );
}
```

---

## Styling Guidelines

### Tailwind CSS

Use Tailwind utility classes for styling:

```tsx
<button className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors">
  Click Me
</button>
```

### Common Patterns

**Card Container:**
```tsx
<div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
  {/* Content */}
</div>
```

**Input Field:**
```tsx
<input
  type="text"
  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
  placeholder="Enter value"
/>
```

**Loading Spinner:**
```tsx
<div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
```

---

## Source Settings Feature

### Overview

The source settings feature allows users to customize how sources are displayed and fetched:

- **Display Name**: Custom name for sources (instead of URL)
- **Fetch Delay**: Time to wait after fetching from a source
- **Priority**: Order in which sources are fetched (lower = first)
- **Max Posts**: Maximum posts to fetch (future feature)

### Components

#### SourceSettingsEditor

A modal component for editing source settings:

```tsx
import SourceSettingsEditor from '../components/SourceSettingsEditor';

function MyComponent() {
  const [editingSource, setEditingSource] = useState<SourceWithSettings | null>(null);

  return (
    <>
      <button onClick={() => setEditingSource(someSource)}>
        Edit Settings
      </button>

      {editingSource && (
        <SourceSettingsEditor
          source={editingSource}
          onClose={() => setEditingSource(null)}
          onSave={() => {
            // Reload data
            loadSources();
          }}
        />
      )}
    </>
  );
}
```

### API Usage

#### Get Source Settings

```typescript
const response = await apiService.getSourceSettings(sourceId);
if (response.success) {
  console.log(response.settings);
  // { display_name: "TechCrunch", fetch_delay_seconds: 5, priority: 1 }
}
```

#### Update Source Settings

```typescript
const response = await apiService.updateSourceSettings(sourceId, {
  display_name: "My Custom Name",
  priority: 5,
  fetch_delay_seconds: 10
});
```

#### Get All Sources with Settings

```typescript
const response = await apiService.getSourcesWithSettings();
if (response.success) {
  response.sources.forEach(source => {
    console.log(source.settings.display_name || source.handle_or_url);
  });
}
```

### Display Name in UI

Sources should display their custom name if set:

```tsx
{source.display_name || source.handle_or_url}
```

This pattern is used in:
- `DailyBriefing.tsx` - Sources sidebar
- `SourcesConfig.tsx` - Source list

### Settings Button Integration

Add a settings button next to sources:

```tsx
import { Settings } from 'lucide-react';

{findDbSource(platform, source.id) && (
  <button
    onClick={() => handleSettingsClick(platform, source.id)}
    className="inline-flex items-center justify-center w-9 h-9 rounded-md border border-gray-300 text-gray-600 hover:bg-gray-50"
    title="Source Settings"
  >
    <Settings className="w-4 h-4" />
  </button>
)}
```

---

## State Management

### Common Patterns

**Loading State:**
```tsx
const [isLoading, setIsLoading] = useState(false);

const fetchData = async () => {
  setIsLoading(true);
  try {
    // Fetch data
  } finally {
    setIsLoading(false);
  }
};
```

**Error Handling:**
```tsx
const [error, setError] = useState<string | null>(null);

try {
  // Operation
  setError(null);
} catch (err) {
  setError(err instanceof Error ? err.message : 'Unknown error');
}
```

**Caching:**
```tsx
const [cache, setCache] = useState<Record<string, Data>>({});

const getData = async (id: string) => {
  if (cache[id]) {
    console.log('Using cached data');
    return cache[id];
  }

  const data = await fetchData(id);
  setCache(prev => ({ ...prev, [id]: data }));
  return data;
};
```

---

## UI Design Principles

### 1. Consistency

- Use consistent spacing, colors, and typography
- Follow existing patterns in the codebase
- Reuse components when possible

### 2. Feedback

- Show loading states for async operations
- Display success/error messages
- Use visual feedback for interactions (hover, active states)

### 3. Accessibility

- Use semantic HTML
- Add appropriate ARIA labels
- Ensure keyboard navigation works
- Maintain good color contrast

### 4. Responsiveness

- Use responsive utilities (`md:`, `lg:`, etc.)
- Test on different screen sizes
- Consider mobile-first design

---

## Common UI Components

### Modal Pattern

```tsx
{isOpen && (
  <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
    <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <h2 className="text-lg font-semibold">Modal Title</h2>
        <button onClick={onClose}>
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Content */}
      <div className="p-4">
        {/* Your content */}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-end gap-2 p-4 border-t bg-gray-50">
        <button onClick={onClose}>Cancel</button>
        <button onClick={onSave}>Save</button>
      </div>
    </div>
  </div>
)}
```

### Button Variants

```tsx
// Primary
<button className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">
  Primary Action
</button>

// Secondary
<button className="px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200">
  Secondary Action
</button>

// Danger
<button className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700">
  Delete
</button>

// Icon Button
<button className="w-9 h-9 flex items-center justify-center rounded-md border border-gray-300 hover:bg-gray-50">
  <Settings className="w-4 h-4" />
</button>
```

### Toast Notifications

Use `sonner` for toast notifications:

```tsx
import { toast } from 'sonner';

// Success
toast.success('Settings saved successfully');

// Error
toast.error('Failed to save settings');

// Info
toast.info('Loading data...');
```

---

## Debugging Tips

### Console Logging

Use descriptive console logs:

```tsx
console.log('📋 Loading sources...');
console.log('✅ Loaded 5 sources');
console.log('❌ Failed to load:', error);
console.log('⚡ Using cached data');
```

### React DevTools

- Inspect component state and props
- Track re-renders and performance
- Debug context and hooks

### Network Tab

- Verify API requests and responses
- Check request payloads
- Monitor response times

---

## Best Practices

1. **Always handle errors** - Display user-friendly error messages
2. **Show loading states** - Don't leave users guessing
3. **Use TypeScript** - Define types for all data structures
4. **Keep components focused** - One responsibility per component
5. **Extract reusable logic** - Use custom hooks for shared logic
6. **Test in browser** - Check console for errors and warnings
7. **Follow naming conventions** - Use descriptive names
8. **Document complex logic** - Add comments for non-obvious code
