import React, { useState, useEffect } from 'react';
import { Plus } from 'lucide-react';
import { useApi } from '../services/ApiContext';
import { Button, Dialog, DialogContent, DialogFooter, FilterChip, Input } from './ui';
import { SubstackHowTo, cookieValue, isSubstackUrl, useConnections, useSaveCredential } from './connections';
import { errorMessage } from '../lib/apiError';

type SourceState = 'enabled' | 'disabled' | 'error';

interface Template {
  id: string;
  name: string;
  platform: string;
  // None: the template always builds one address (Pipecraft, Gwern…), so there is no field.
  variableName?: string;
  // An empty variable still builds a source (GitHub Trending: all languages).
  optionalVariable?: boolean;
  variableLabel?: string;
  placeholder?: string;
  helperText?: string;
  buildHandle: (value: string) => string;
  buildDisplayName?: (value: string) => string;
  defaultSettings: {
    fetch_delay_seconds: number;
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
    },
  },
  {
    id: 'lesswrong',
    name: 'LessWrong',
    platform: 'rss',
    helperText: 'LessWrong\'s posts; the archive reaches far back.',
    buildHandle: () => 'https://www.lesswrong.com/feed.xml',
    buildDisplayName: () => 'LessWrong',
    defaultSettings: {
      fetch_delay_seconds: 1,
    },
  },
  {
    id: 'gwern',
    name: 'Gwern',
    platform: 'rss',
    helperText: 'Gwern\'s essays from gwern.net; the archive reaches every page.',
    buildHandle: () => 'https://gwern.net',
    buildDisplayName: () => 'Gwern',
    defaultSettings: {
      fetch_delay_seconds: 1,
    },
  },
  {
    id: 'dario-amodei',
    name: 'Dario Amodei Blog',
    platform: 'rss',
    helperText: 'Dario Amodei\'s essays and posts from darioamodei.com.',
    buildHandle: () => 'https://darioamodei.com',
    buildDisplayName: () => 'Dario Amodei',
    defaultSettings: {
      fetch_delay_seconds: 1,
    },
  },
  {
    id: 'pipecraft',
    name: 'Pipecraft (Tornike Gomareli)',
    platform: 'rss',
    helperText: 'Tornike Gomareli\'s posts and essays from pipecraft.me, read in full.',
    buildHandle: () => 'https://www.pipecraft.me/',
    buildDisplayName: () => 'Pipecraft',
    defaultSettings: {
      fetch_delay_seconds: 1,
    },
  },
  {
    id: 'github-trending',
    name: 'GitHub Trending',
    platform: 'rss',
    variableName: 'language',
    variableLabel: 'Language',
    optionalVariable: true,
    placeholder: 'All languages',
    helperText: 'Today\'s trending repositories, each a post with its README, from the GitHubTrendingRSS feed (github.com has none). Leave empty for all languages. For the week or the month, change daily/ to weekly/ or monthly/ in the URL.',
    buildHandle: (value) => {
      const language = value.trim().toLowerCase().replace(/\s+/g, '-');
      return `https://mshibanami.github.io/GitHubTrendingRSS/daily/${encodeURIComponent(language || 'all')}.xml`;
    },
    buildDisplayName: (value) => (value.trim() ? `GitHub Trending · ${value.trim()}` : 'GitHub Trending'),
    defaultSettings: {
      fetch_delay_seconds: 1,
    },
  },
  {
    id: 'deeplearning-batch',
    name: 'DeepLearning.AI The Batch',
    platform: 'rss',
    helperText: 'Every issue of The Batch newsletter; the archive reaches its first issue.',
    buildHandle: () => 'https://www.deeplearning.ai/the-batch/',
    buildDisplayName: () => 'DeepLearning.AI The Batch',
    defaultSettings: {
      fetch_delay_seconds: 1,
    },
  },
  {
    id: 'philschmid-cloud-attention',
    name: 'Cloud Attention',
    platform: 'rss',
    helperText: 'Every issue of Phil Schmid\'s Cloud Attention newsletter, read in full.',
    buildHandle: () => 'https://www.philschmid.de/cloud-attention',
    buildDisplayName: () => 'Phil Schmid Cloud Attention',
    defaultSettings: {
      fetch_delay_seconds: 1,
    },
  },
  {
    id: 'ztm-ml-monthly',
    name: 'ZTM AI & ML Monthly',
    platform: 'rss',
    helperText: 'Every issue of Zero To Mastery\'s AI & ML Monthly newsletter, read in full.',
    buildHandle: () => 'https://zerotomastery.io/newsletters/machine-learning-monthly/1/',
    buildDisplayName: () => 'Zero To Mastery AI & ML Monthly',
    defaultSettings: {
      fetch_delay_seconds: 1,
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
    },
  },
];

/** The address a template always builds, whatever its field (Pipecraft, Gwern…); null when the
 *  field changes it (Nitter, YouTube, GitHub Trending), so it can be added once per value. */
function fixedHandle(template: Template): string | null {
  const handle = template.buildHandle('a');
  return handle === template.buildHandle('b') ? handle : null;
}

/** An address compared loosely: no scheme, www. or trailing slash, any case. */
function sameAddress(address: string): string {
  return address.trim().toLowerCase().replace(/^https?:\/\/(www\.)?/, '').replace(/\/+$/, '');
}

interface AddSourceModalProps {
  platform: string;
  /** The addresses already in the sources: a one-address template among them is not offered. */
  existingAddresses?: readonly string[];
  onClose: () => void;
  onAdd: (source: {
    handle_or_url: string;
    display_name: string;
    fetch_delay_seconds: number;
    state: SourceState;
  }) => void;
}

export default function AddSourceModal({ platform, existingAddresses = [], onClose, onAdd }: AddSourceModalProps) {
  const api = useApi();
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [templateVariable, setTemplateVariable] = useState('');
  const [handleOrUrl, setHandleOrUrl] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [displayNameManuallyEdited, setDisplayNameManuallyEdited] = useState(false);
  const [fetchDelay, setFetchDelay] = useState(1);
  const [isResolvingChannel, setIsResolvingChannel] = useState(false);
  const [resolvedChannelName, setResolvedChannelName] = useState<string | null>(null);
  // A Substack URL offers the paid-subscription cookie; it saves to Connections, shared by every Substack source.
  const substack = isSubstackUrl(handleOrUrl);
  const connections = useConnections(substack);
  const substackSid = connections.data?.providers.find((p) => p.provider === 'substack')?.fields.find((f) => f.key === 'sid');
  const [sid, setSid] = useState('');
  const [sidError, setSidError] = useState<string | null>(null);
  const saveSid = useSaveCredential();
  
  const youtubeLookupValue = selectedTemplate?.id === 'youtube-handle'
    ? (templateVariable.trim() ? selectedTemplate.buildHandle(templateVariable.trim()) : '')
    : (platform === 'youtube' ? handleOrUrl.trim() : '');

  // Get templates for this platform, less the one-address ones already added (Pipecraft, Gwern…).
  const added = new Set(existingAddresses.map(sameAddress));
  const availableTemplates = TEMPLATES.filter((t) => {
    const fixed = fixedHandle(t);
    return t.platform === platform && !(fixed && added.has(sameAddress(fixed)));
  });

  // Update URL when template variable changes
  useEffect(() => {
    if (selectedTemplate && (templateVariable || selectedTemplate.optionalVariable)) {
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
      const preview = await api.listYouTubeChannelVideos(youtubeLookupValue, 1);
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
  }, [api, platform, youtubeLookupValue, displayNameManuallyEdited]);

  const handleTemplateClick = (template: Template) => {
    setSelectedTemplate(template);
    setFetchDelay(template.defaultSettings.fetch_delay_seconds);
    // Clear previous values
    setTemplateVariable('');
    const builds = !template.variableName || Boolean(template.optionalVariable);
    setHandleOrUrl(builds ? template.buildHandle('') : '');
    setDisplayName(builds ? (template.buildDisplayName?.('') || '') : '');
    setDisplayNameManuallyEdited(false); // Reset manual edit flag
    setIsResolvingChannel(false);
    setResolvedChannelName(null);
  };

  const handleAdd = async () => {
    if (!handleOrUrl.trim()) {
      return;
    }
    const cookie = substack ? cookieValue(sid) : '';
    if (cookie) {
      setSidError(null);
      try {
        await saveSid.mutateAsync({ provider: 'substack', key: 'sid', value: cookie });
        setSid('');
      } catch (err) {
        setSidError(errorMessage(err));
        return;
      }
    }

    onAdd({
      handle_or_url: handleOrUrl.trim(),
      display_name: displayName.trim(),
      fetch_delay_seconds: fetchDelay,
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
          onSubmit={(event) => { event.preventDefault(); if (handleOrUrl.trim()) void handleAdd(); }}
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
              {selectedTemplate.variableName ? (
                <>
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
                    → {selectedTemplate.buildHandle(templateVariable || (selectedTemplate.optionalVariable ? '' : `{${selectedTemplate.variableName}}`))}
                  </p>
                </>
              ) : null}
              {selectedTemplate.helperText && <p className={selectedTemplate.variableName ? hint : 'text-[0.8125rem] text-fg-2'}>{selectedTemplate.helperText}</p>}
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

          {substack ? (
            <div className="space-y-2 rounded-md border border-line p-3" data-testid="substack-sid">
              {substackSid?.set ? (
                <p className="text-[0.8125rem] text-fg-2">
                  Paid posts: your Substack session is set in Connections
                  {substackSid.last4 ? <span className="font-mono"> (••••{substackSid.last4})</span> : null}. Every Substack source shares it.
                </p>
              ) : (
                <>
                  <label htmlFor="substack_sid" className={label}>
                    Paid subscription? Add your substack.sid <span className="font-normal text-fg-3">(optional)</span>
                  </label>
                  <Input
                    id="substack_sid"
                    type="password"
                    value={sid}
                    onChange={(e) => setSid(e.target.value)}
                    placeholder="Paste the substack.sid cookie"
                    autoComplete="off"
                    spellCheck={false}
                    aria-invalid={sidError ? true : undefined}
                    className="font-mono"
                  />
                  <p className={hint}>Saved to Connections and shared by every Substack source. Without it, paid posts arrive as teasers.</p>
                  <SubstackHowTo />
                  {sidError ? (
                    <p role="alert" className="text-[0.75rem] text-fg [overflow-wrap:anywhere]">
                      <span aria-hidden="true" className="mr-1 font-semibold">×</span>{sidError}
                    </p>
                  ) : null}
                </>
              )}
            </div>
          ) : null}

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
            </div>
          </details>

          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={!handleOrUrl.trim() || saveSid.isPending}>
              <Plus aria-hidden="true" /> Add source
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
