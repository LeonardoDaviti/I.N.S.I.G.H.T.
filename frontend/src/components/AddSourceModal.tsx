import React, { useState, useRef, useEffect } from 'react';
import { X, Plus } from 'lucide-react';
import type { SourceState } from '../types';
import { apiService } from '../services/api';

interface Template {
  id: string;
  name: string;
  color: string;
  platform: string;
  variableName: string;
  defaultVariableValue?: string;
  variableLabel?: string;
  placeholder?: string;
  helperText?: string;
  buildHandle: (value: string) => string;
  buildDisplayName?: (value: string) => string;
  defaultSettings: {
    fetch_delay_seconds: number;
    priority: number;
    max_posts_per_fetch: number;
  };
}

// Hardcoded templates
const TEMPLATES: Template[] = [
  {
    id: 'nitter',
    name: 'Nitter',
    color: '#FF6C60',
    platform: 'rss',
    variableName: 'username',
    variableLabel: 'Username',
    placeholder: 'Enter username...',
    helperText: 'Creates a source like https://nitter.local/{username}/rss',
    buildHandle: (value) => `https://nitter.local/${value.replace(/^@/, '').trim()}/rss`,
    buildDisplayName: (value) => value.replace(/^@/, '').trim(),
    defaultSettings: {
      fetch_delay_seconds: 10,
      priority: 999,
      max_posts_per_fetch: 50,
    },
  },
  {
    id: 'telegram-rss',
    name: 'Telegram RSS',
    color: '#0EA5E9',
    platform: 'rss',
    variableName: 'username',
    variableLabel: 'Channel Username',
    placeholder: 'Enter channel username...',
    helperText: 'Creates a source like https://telegram.local/rss/seeallochnaya?limit=50',
    buildHandle: (value) => `https://telegram.local/rss/${value.replace(/^@/, '').trim()}?limit=50`,
    buildDisplayName: (value) => value.replace(/^@/, '').trim(),
    defaultSettings: {
      fetch_delay_seconds: 5,
      priority: 999,
      max_posts_per_fetch: 50,
    },
  },
  {
    id: 'lesswrong',
    name: 'LessWrong',
    color: '#2563EB',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'lesswrong',
    variableLabel: 'Archive Scope',
    placeholder: 'Main LessWrong archive',
    helperText: 'Uses the custom LessWrong adapter for live fetch plus deep archive through GraphQL.',
    buildHandle: () => 'https://www.lesswrong.com/feed.xml',
    buildDisplayName: () => 'LessWrong',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 20,
    },
  },
  {
    id: 'gwern',
    name: 'Gwern',
    color: '#111827',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'gwern',
    variableLabel: 'Archive Scope',
    placeholder: 'Main Gwern archive',
    helperText: 'Uses the custom Gwern adapter for sitemap-backed archive depth and newest-page live fetch.',
    buildHandle: () => 'https://gwern.net',
    buildDisplayName: () => 'Gwern',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 20,
    },
  },
  {
    id: 'dario-amodei',
    name: 'Dario Amodei Blog',
    color: '#334155',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'dario',
    variableLabel: 'Archive Scope',
    placeholder: 'Dario Amodei personal site',
    helperText: 'Uses the custom Dario adapter for essays and posts from darioamodei.com.',
    buildHandle: () => 'https://darioamodei.com',
    buildDisplayName: () => 'Dario Amodei',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 10,
    },
  },
  {
    id: 'deeplearning-batch',
    name: 'DeepLearning.AI The Batch',
    color: '#F65B66',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'the-batch',
    variableLabel: 'Archive Scope',
    placeholder: 'The Batch newsletter',
    helperText: 'Uses the custom The Batch adapter with sitemap-backed issue discovery and full newsletter archive.',
    buildHandle: () => 'https://www.deeplearning.ai/the-batch/',
    buildDisplayName: () => 'DeepLearning.AI The Batch',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 10,
    },
  },
  {
    id: 'philschmid-cloud-attention',
    name: 'Cloud Attention',
    color: '#10B981',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'cloud-attention',
    variableLabel: 'Archive Scope',
    placeholder: 'Phil Schmid newsletter archive',
    helperText: 'Uses the custom Cloud Attention adapter for paginated issue discovery and full issue ingestion.',
    buildHandle: () => 'https://www.philschmid.de/cloud-attention',
    buildDisplayName: () => 'Phil Schmid Cloud Attention',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 10,
    },
  },
  {
    id: 'ztm-ml-monthly',
    name: 'ZTM AI & ML Monthly',
    color: '#EC4899',
    platform: 'rss',
    variableName: 'site',
    defaultVariableValue: 'machine-learning-monthly',
    variableLabel: 'Archive Scope',
    placeholder: 'Zero To Mastery monthly AI newsletter',
    helperText: 'Uses the custom ZTM adapter for full AI & ML Monthly archive discovery and post hydration.',
    buildHandle: () => 'https://zerotomastery.io/newsletters/machine-learning-monthly/1/',
    buildDisplayName: () => 'Zero To Mastery AI & ML Monthly',
    defaultSettings: {
      fetch_delay_seconds: 1,
      priority: 999,
      max_posts_per_fetch: 10,
    },
  },
  {
    id: 'youtube-handle',
    name: 'YouTube',
    color: '#EF4444',
    platform: 'youtube',
    variableName: 'channel',
    variableLabel: 'Channel Handle',
    placeholder: 'Enter channel handle...',
    helperText: 'Use the YouTube @handle. Example: LAWRENCESYSTEMS',
    buildHandle: (value) => `https://www.youtube.com/@${value.replace(/^@/, '').trim()}`,
    buildDisplayName: (value) => `@${value.replace(/^@/, '').trim()}`,
    defaultSettings: {
      fetch_delay_seconds: 2,
      priority: 999,
      max_posts_per_fetch: 5,
    },
  },
];

interface AddSourceModalProps {
  platform: string;
  onClose: () => void;
  onAdd: (source: {
    handle_or_url: string;
    display_name: string;
    fetch_delay_seconds: number;
    priority: number;
    max_posts_per_fetch: number;
    state: SourceState;
  }) => void;
}

export default function AddSourceModal({ platform, onClose, onAdd }: AddSourceModalProps) {
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [templateVariable, setTemplateVariable] = useState('');
  const [handleOrUrl, setHandleOrUrl] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [displayNameManuallyEdited, setDisplayNameManuallyEdited] = useState(false);
  const [fetchDelay, setFetchDelay] = useState(1);
  const [priority, setPriority] = useState(999);
  const [maxPosts, setMaxPosts] = useState(50);
  const [isResolvingChannel, setIsResolvingChannel] = useState(false);
  const [resolvedChannelName, setResolvedChannelName] = useState<string | null>(null);
  
  const modalRef = useRef<HTMLDivElement>(null);
  const youtubeLookupValue = selectedTemplate?.id === 'youtube-handle'
    ? (templateVariable.trim() ? selectedTemplate.buildHandle(templateVariable.trim()) : '')
    : (platform === 'youtube' ? handleOrUrl.trim() : '');

  // Get templates for this platform
  const availableTemplates = TEMPLATES.filter(t => t.platform === platform);

  // Handle click outside to close
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(event.target as Node)) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose]);

  // Update URL when template variable changes
  useEffect(() => {
    if (selectedTemplate && templateVariable) {
      const normalized = templateVariable.trim();
      const sourceValue = selectedTemplate.buildHandle(normalized);
      setHandleOrUrl(sourceValue);
      
      // Auto-fill display name if user hasn't manually edited it
      if (!displayNameManuallyEdited) {
        setDisplayName(selectedTemplate.buildDisplayName?.(normalized) || normalized);
      }
    }
  }, [selectedTemplate, templateVariable, displayNameManuallyEdited]);

  useEffect(() => {
    if (platform !== 'youtube' || !youtubeLookupValue) {
      setIsResolvingChannel(false);
      setResolvedChannelName(null);
      return;
    }

    let cancelled = false;
    setIsResolvingChannel(true);

    const timeout = window.setTimeout(async () => {
      const preview = await apiService.listYouTubeChannelVideos(youtubeLookupValue, 1);
      if (cancelled) return;

      const channelTitle = preview.videos?.[0]?.channel_title?.trim();
      if (channelTitle) {
        setResolvedChannelName(channelTitle);
        if (!displayNameManuallyEdited) {
          setDisplayName(channelTitle);
        }
      } else {
        setResolvedChannelName(null);
      }
      setIsResolvingChannel(false);
    }, 450);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [platform, youtubeLookupValue, displayNameManuallyEdited]);

  const handleTemplateClick = (template: Template) => {
    setSelectedTemplate(template);
    setFetchDelay(template.defaultSettings.fetch_delay_seconds);
    setPriority(template.defaultSettings.priority);
    setMaxPosts(template.defaultSettings.max_posts_per_fetch);
    // Clear previous values
    const initialValue = template.defaultVariableValue || '';
    setTemplateVariable(initialValue);
    setHandleOrUrl(initialValue ? template.buildHandle(initialValue) : '');
    setDisplayName(initialValue ? (template.buildDisplayName?.(initialValue) || initialValue) : '');
    setDisplayNameManuallyEdited(false); // Reset manual edit flag
    setIsResolvingChannel(false);
    setResolvedChannelName(null);
  };

  const handleAdd = () => {
    if (!handleOrUrl.trim()) {
      return;
    }

    onAdd({
      handle_or_url: handleOrUrl.trim(),
      display_name: displayName.trim(),
      fetch_delay_seconds: fetchDelay,
      priority,
      max_posts_per_fetch: maxPosts,
      state: 'enabled',
    });

    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div ref={modalRef} className="bg-white rounded-lg shadow-xl max-w-md w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 sticky top-0 bg-white">
          <h2 className="text-lg font-semibold text-gray-900">Add New Source</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Templates Section */}
          {availableTemplates.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Templates
              </label>
              <div className="flex flex-wrap gap-2">
                {availableTemplates.map((template) => (
                  <button
                    key={template.id}
                    onClick={() => handleTemplateClick(template)}
                    className={`px-4 py-2 rounded-lg font-medium text-sm transition-all ${
                      selectedTemplate?.id === template.id
                        ? 'bg-white shadow-md'
                        : 'bg-white hover:shadow-md'
                    }`}
                    style={{
                      border: `2px solid ${template.color}`,
                      color: template.color,
                      boxShadow: selectedTemplate?.id === template.id
                        ? `0 0 12px ${template.color}40`
                        : 'none',
                    }}
                  >
                    {template.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Template Variable Input */}
          {selectedTemplate && (
            <div className="bg-blue-50 border border-blue-200 rounded-md p-3">
              <label htmlFor="template-var" className="block text-sm font-medium text-blue-900 mb-1">
                {(selectedTemplate.variableLabel || selectedTemplate.variableName.charAt(0).toUpperCase() + selectedTemplate.variableName.slice(1))} (for {selectedTemplate.name})
              </label>
              <input
                id="template-var"
                type="text"
                value={templateVariable}
                onChange={(e) => setTemplateVariable(e.target.value)}
                placeholder={selectedTemplate.placeholder || `Enter ${selectedTemplate.variableName}...`}
                className="w-full px-3 py-2 border border-blue-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
              />
              <p className="text-xs text-blue-700 mt-1 break-all">
                → {selectedTemplate.buildHandle(templateVariable || `{${selectedTemplate.variableName}}`)}
              </p>
              {selectedTemplate.helperText && (
                <p className="text-xs text-blue-700/80 mt-1">
                  {selectedTemplate.helperText}
                </p>
              )}
              {platform === 'youtube' && youtubeLookupValue && (
                <p className="text-xs mt-2 text-red-700">
                  {isResolvingChannel
                    ? 'Resolving channel title...'
                    : resolvedChannelName
                      ? `Resolved channel: ${resolvedChannelName}`
                      : 'Could not resolve channel title yet. The handle will still work as a source.'}
                </p>
              )}
            </div>
          )}

          {/* Divider */}
          {availableTemplates.length > 0 && (
            <div className="flex items-center gap-3">
              <div className="flex-1 border-t border-gray-300"></div>
              <span className="text-xs text-gray-500 uppercase">or enter manually</span>
              <div className="flex-1 border-t border-gray-300"></div>
            </div>
          )}

          {/* Handle or URL */}
          <div>
            <label htmlFor="handle_or_url" className="block text-sm font-medium text-gray-700 mb-1">
              Handle or URL
            </label>
            <input
              id="handle_or_url"
              type="text"
              value={handleOrUrl}
              onChange={(e) => setHandleOrUrl(e.target.value)}
              placeholder="Enter source URL or handle"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
              disabled={!!selectedTemplate && !!templateVariable}
            />
          </div>

          {/* Display Name */}
          <div>
            <label htmlFor="display_name" className="block text-sm font-medium text-gray-700 mb-1">
              Display Name
            </label>
            <input
              id="display_name"
              type="text"
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                setDisplayNameManuallyEdited(true); // Mark as manually edited
              }}
              placeholder="Leave empty to use URL/handle"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
            />
            <p className="text-xs text-gray-500 mt-1">
              Optional: Friendly name for this source
            </p>
          </div>

          {/* Fetch Delay */}
          <div>
            <label htmlFor="fetch_delay" className="block text-sm font-medium text-gray-700 mb-1">
              Fetch Delay (seconds)
            </label>
            <input
              id="fetch_delay"
              type="number"
              min="0"
              max="60"
              value={fetchDelay}
              onChange={(e) => setFetchDelay(parseInt(e.target.value) || 1)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
            />
            <p className="text-xs text-gray-500 mt-1">
              Time to wait after fetching from this source
            </p>
          </div>

          {/* Priority */}
          <div>
            <label htmlFor="priority" className="block text-sm font-medium text-gray-700 mb-1">
              Priority
            </label>
            <input
              id="priority"
              type="number"
              min="1"
              max="9999"
              value={priority}
              onChange={(e) => setPriority(parseInt(e.target.value) || 999)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
            />
            <p className="text-xs text-gray-500 mt-1">
              Lower number = higher priority (fetched first)
            </p>
          </div>

          {/* Max Posts Per Fetch */}
          <div>
            <label htmlFor="max_posts" className="block text-sm font-medium text-gray-700 mb-1">
              Max Posts Per Fetch
            </label>
            <input
              id="max_posts"
              type="number"
              min="1"
              max="200"
              value={maxPosts}
              onChange={(e) => setMaxPosts(parseInt(e.target.value) || 50)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
              disabled
            />
            <p className="text-xs text-gray-500 mt-1">
              ⚠️ Not enforced (future feature)
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 p-4 border-t border-gray-200 bg-gray-50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleAdd}
            disabled={!handleOrUrl.trim()}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            Add Source
          </button>
        </div>
      </div>
    </div>
  );
}
