import React, { useState, useEffect } from 'react';
import { Plus } from 'lucide-react';
import type { SourceState } from '../types';
import { apiService } from '../services/api';
import { Button, Dialog, DialogContent, DialogFooter, FilterChip, Input } from './ui';

interface Template {
  id: string;
  name: string;
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
  
  const youtubeLookupValue = selectedTemplate?.id === 'youtube-handle'
    ? (templateVariable.trim() ? selectedTemplate.buildHandle(templateVariable.trim()) : '')
    : (platform === 'youtube' ? handleOrUrl.trim() : '');

  // Get templates for this platform
  const availableTemplates = TEMPLATES.filter(t => t.platform === platform);

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

  const hint = 'mt-1 text-[0.75rem] text-fg-3';
  const label = 'mb-1.5 block text-[0.8125rem] font-medium text-fg';

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent title="Add source" className="w-[min(32rem,calc(100vw-2rem))]">
        <form
          className="mt-4 space-y-5"
          onSubmit={(event) => { event.preventDefault(); if (handleOrUrl.trim()) handleAdd(); }}
        >
          {availableTemplates.length > 0 && (
            <div>
              <span className={label}>Start from a template</span>
              <div className="flex flex-wrap gap-2">
                {availableTemplates.map((template) => (
                  <FilterChip
                    key={template.id}
                    selected={selectedTemplate?.id === template.id}
                    onClick={() => handleTemplateClick(template)}
                  >
                    {template.name}
                  </FilterChip>
                ))}
              </div>
            </div>
          )}

          {selectedTemplate && (
            <div className="rounded-md border border-line bg-surface p-3">
              <label htmlFor="template-var" className={label}>
                {(selectedTemplate.variableLabel || selectedTemplate.variableName.charAt(0).toUpperCase() + selectedTemplate.variableName.slice(1))} (for {selectedTemplate.name})
              </label>
              <Input
                id="template-var"
                value={templateVariable}
                onChange={(e) => setTemplateVariable(e.target.value)}
                placeholder={selectedTemplate.placeholder || `Enter ${selectedTemplate.variableName}…`}
              />
              <p className="mt-1.5 font-mono text-[0.75rem] text-fg-2 [overflow-wrap:anywhere]">
                → {selectedTemplate.buildHandle(templateVariable || `{${selectedTemplate.variableName}}`)}
              </p>
              {selectedTemplate.helperText && <p className={hint}>{selectedTemplate.helperText}</p>}
              {platform === 'youtube' && youtubeLookupValue && (
                <p className="mt-2 text-[0.75rem] text-fg-2">
                  {isResolvingChannel
                    ? 'Resolving channel title…'
                    : resolvedChannelName
                      ? `Resolved channel: ${resolvedChannelName}`
                      : 'Could not resolve the channel title yet. The handle still works as a source.'}
                </p>
              )}
            </div>
          )}

          {availableTemplates.length > 0 && (
            <div className="flex items-center gap-3" aria-hidden="true">
              <div className="flex-1 border-t border-line" />
              <span className="text-[0.75rem] text-fg-3">or enter it yourself</span>
              <div className="flex-1 border-t border-line" />
            </div>
          )}

          <div>
            <label htmlFor="handle_or_url" className={label}>Feed URL or handle</label>
            <Input
              id="handle_or_url"
              value={handleOrUrl}
              onChange={(e) => setHandleOrUrl(e.target.value)}
              placeholder="https://example.com/feed.xml"
              disabled={!!selectedTemplate && !!templateVariable}
              autoComplete="off"
            />
          </div>

          <div>
            <label htmlFor="display_name" className={label}>Name</label>
            <Input
              id="display_name"
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                setDisplayNameManuallyEdited(true);
              }}
              placeholder="Optional; derived from the URL when empty"
            />
          </div>

          <details className="group">
            <summary className="cursor-pointer select-none text-[0.8125rem] text-fg-2 hover:text-fg">Advanced</summary>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="fetch_delay" className={label}>Fetch delay (seconds)</label>
                <Input
                  id="fetch_delay"
                  type="number"
                  min="0"
                  max="60"
                  value={fetchDelay}
                  onChange={(e) => setFetchDelay(parseInt(e.target.value) || 1)}
                  className="tabular-nums"
                />
                <p className={hint}>Wait after fetching this source.</p>
              </div>
              <div>
                <label htmlFor="priority" className={label}>Priority</label>
                <Input
                  id="priority"
                  type="number"
                  min="1"
                  max="9999"
                  value={priority}
                  onChange={(e) => setPriority(parseInt(e.target.value) || 999)}
                  className="tabular-nums"
                />
                <p className={hint}>Lower is fetched first.</p>
              </div>
              <div>
                <label htmlFor="max_posts" className={label}>Max posts per fetch</label>
                <Input
                  id="max_posts"
                  type="number"
                  min="1"
                  max="200"
                  value={maxPosts}
                  onChange={(e) => setMaxPosts(parseInt(e.target.value) || 50)}
                  className="tabular-nums"
                  disabled
                />
                <p className={hint}>Not enforced yet.</p>
              </div>
            </div>
          </details>

          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={!handleOrUrl.trim()}>
              <Plus aria-hidden="true" /> Add source
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
