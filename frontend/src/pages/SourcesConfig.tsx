import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/api';
import type { SourceConfig, SourceItem, SourceState } from '../types';
import { Loader2, Save, Plus, Trash2, ChevronLeft, Rss, Youtube, Send, MessageSquare, FileText, Settings, GripVertical } from 'lucide-react';
import { toast } from 'sonner';
import SourceSettingsEditor from '../components/SourceSettingsEditor';
import type { SourceWithSettings } from '../services/api';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

type PlatformKey = keyof SourceConfig['platforms'];

type SourcesConfigProps = {
  embedded?: boolean;
  onClose?: () => void;
};

// Extended source item with priority and database info
interface SourceItemWithPriority extends SourceItem {
  priority: number;
  displayName?: string;
  dbId?: string;
}

// Sortable source item component
interface SortableSourceItemProps {
  source: SourceItemWithPriority;
  onToggleState: () => void;
  onUpdate: (value: string) => void;
  onRemove: () => void;
  onSettingsClick: () => void;
  hasDbSource: boolean;
  getStateStyle: (state: SourceState) => string;
}

function SortableSourceItem({
  source,
  onToggleState,
  onUpdate,
  onRemove,
  onSettingsClick,
  hasDbSource,
  getStateStyle,
}: SortableSourceItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: source.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} className="flex items-center gap-2">
      {/* Drag Handle */}
      <button
        {...attributes}
        {...listeners}
        className="cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-600 flex-shrink-0"
        title="Drag to reorder"
      >
        <GripVertical className="w-5 h-5" />
      </button>

      {/* Priority Number */}
      <button
        onClick={onToggleState}
        className={`inline-flex items-center justify-center w-12 h-9 rounded-md border font-mono text-xs hover:opacity-75 flex-shrink-0 ${getStateStyle(source.state)}`}
        title={`Priority: ${source.priority} | State: ${source.state} - Click to cycle`}
      >
        {source.priority}
      </button>

      {/* Source Input */}
      <input
        value={source.id}
        onChange={(e) => onUpdate(e.target.value)}
        className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm"
        placeholder="Enter source identifier or URL"
      />

      {/* Settings Button */}
      {hasDbSource && (
        <button
          onClick={onSettingsClick}
          className="inline-flex items-center justify-center w-9 h-9 rounded-md border border-gray-300 text-gray-600 hover:bg-gray-50 flex-shrink-0"
          title="Source Settings"
        >
          <Settings className="w-4 h-4" />
        </button>
      )}

      {/* Remove Button */}
      <button
        onClick={onRemove}
        className="inline-flex items-center justify-center w-9 h-9 rounded-md border border-red-300 text-red-600 hover:bg-red-50 flex-shrink-0"
        title="Remove"
      >
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  );
}

export default function SourcesConfig({ embedded = false, onClose }: SourcesConfigProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<SourceConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [pulsing] = useState<Record<string, boolean>>({});
  const [bulkEdit, setBulkEdit] = useState<{ platform: string; text: string } | null>(null);
  const [dbSources, setDbSources] = useState<SourceWithSettings[]>([]);
  const [editingSource, setEditingSource] = useState<SourceWithSettings | null>(null);

  const EXPANDED_KEY = 'insight.sources.expanded';

  // Drag and drop sensors
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const loadExpanded = (keys: string[]): Record<string, boolean> => {
    try {
      const raw = typeof window !== 'undefined' ? localStorage.getItem(EXPANDED_KEY) : null;
      const parsed: Record<string, boolean> | null = raw ? JSON.parse(raw) : null;
      const obj: Record<string, boolean> = {};
      keys.forEach((k) => {
        obj[k] = parsed && typeof parsed[k] === 'boolean' ? parsed[k] : true; // default expanded
      });
      return obj;
    } catch {
      const obj: Record<string, boolean> = {};
      keys.forEach((k) => (obj[k] = true));
      return obj;
    }
  };

  const saveExpanded = (obj: Record<string, boolean>) => {
    try {
      if (typeof window !== 'undefined') localStorage.setItem(EXPANDED_KEY, JSON.stringify(obj));
    } catch {}
  };

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      
      // Fetch both config and database sources
      const [configRes, dbSourcesRes] = await Promise.all([
        apiService.getSources(),
        apiService.getSourcesWithSettings()
      ]);
      
      if (mounted) {
        if (configRes.success && configRes.data) {
          const normalizedConfig = { ...configRes.data as SourceConfig };

          Object.keys(normalizedConfig.platforms).forEach(platformKey =>{
            const platform = normalizedConfig.platforms[platformKey];
            platform.sources = normalizeSources(platform.sources);
          })

          setConfig(normalizedConfig);
        } else {
          toast.error(configRes.error || 'Failed to load sources configuration');
        }
        
        if (dbSourcesRes.success) {
          setDbSources(dbSourcesRes.sources);
        }
        
        setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, []);

  const platforms = useMemo(() => Object.keys(config?.platforms || {}), [config]) as PlatformKey[];

  useEffect(() => {
    // Initialize expanded state when config loads
    if (platforms.length) {
      const init = loadExpanded(platforms as string[]);
      setExpanded(init);
    }
  }, [platforms.length]);

  const platformIcon: Record<string, ReactNode> = {
    rss: <Rss className="w-5 h-5" />,
    youtube: <Youtube className="w-5 h-5" />,
    telegram: <Send className="w-5 h-5" />,
    reddit: <MessageSquare className="w-5 h-5" />,
  };

  function normalizeSources(list: Array<string | SourceItem>): SourceItem[] {
    if (!Array.isArray(list)) return [];
    return list.map((entry) => {
      if (typeof entry === 'string') {
        return { id: entry, state: 'enabled' as SourceState };
      }
      const id = typeof entry.id === 'string' && entry.id.trim() ? entry.id : String(entry.id ?? '');
      const st: SourceState =
        entry.state === 'disabled' || entry.state === 'only' ? entry.state : 'enabled';
      return { id, state: st };
    });
  }
  
  function denormalizeSources(list: SourceItem[]): Array<string | SourceItem> {
    return list.map((s) => ({ id: s.id, state: s.state }));
  }

  const totalSources = useMemo(() => {
    if (!config) return 0;
    return Object.values(config.platforms).reduce((acc, p) => acc + (p.sources?.length || 0), 0);
  }, [config]);

  const enabledSourcesCount = useMemo(() => {
    if (!config) return 0;
    return Object.values(config.platforms).reduce((acc, p) => {
      // Count sources only if BOTH platform is enabled AND source state is 'enabled'
      if (!p.enabled) return acc;
      const enabledInPlatform = p.sources?.filter(s => s.state === 'enabled').length || 0;
      return acc + enabledInPlatform;
    }, 0);
  }, [config]);

  const togglePlatform = (platform: PlatformKey) => {
    if (!config) return;
    const next = {
      ...config,
      platforms: {
        ...config.platforms,
        [platform]: {
          ...config.platforms[platform],
          enabled: !config.platforms[platform].enabled,
        },
      },
    };
    setConfig(next);
    setDirty(true);
  };

  const addSource = (platform: PlatformKey) => {
    if (!config) return;
    const value = prompt(`Add new source to ${platform}`);
    if (!value) return;
    const next = {
      ...config,
      platforms: {
        ...config.platforms,
        [platform]: {
          ...config.platforms[platform],
          sources: [...config.platforms[platform].sources, { id: value.trim(), state: 'enabled' as SourceState }],
        },
      },
    };
    setConfig(next);
    setDirty(true);
  };

  function findDbSource(platform: string, sourceId: string): SourceWithSettings | undefined {
    return dbSources.find(
      (s) => s.platform === platform && s.handle_or_url === sourceId
    );
  }

  function handleSettingsClick(platform: string, sourceId: string) {
    const dbSource = findDbSource(platform, sourceId);
    if (dbSource) {
      setEditingSource(dbSource);
    } else {
      toast.error('Source not found in database');
    }
  }

  async function handleSettingsSaved() {
    // Reload database sources to get updated settings
    const res = await apiService.getSourcesWithSettings();
    if (res.success) {
      setDbSources(res.sources);
      toast.success('Settings updated successfully');
    }
  }

  // Get sources with priorities for a platform
  const getSourcesWithPriority = (platform: PlatformKey): SourceItemWithPriority[] => {
    if (!config) return [];

    const sources = config.platforms[platform].sources;
    
    return sources.map((source) => {
      const dbSource = findDbSource(platform, source.id);
      return {
        ...source,
        priority: dbSource?.settings?.priority ?? 999,
        displayName: dbSource?.settings?.display_name,
        dbId: dbSource?.id,
      };
    });
  };

  // Get sources sorted by priority for a platform
  const getSortedSources = (platform: PlatformKey): SourceItemWithPriority[] => {
    const sourcesWithPriority = getSourcesWithPriority(platform);
    return [...sourcesWithPriority].sort((a, b) => {
      // Sort by priority first, then by id for stable sort
      if (a.priority !== b.priority) {
        return a.priority - b.priority;
      }
      return a.id.localeCompare(b.id);
    });
  };

  // Handle drag end - update order and priorities
  const handleDragEnd = async (event: DragEndEvent, platform: PlatformKey) => {
    const { active, over } = event;

    if (!over || active.id === over.id) return;

    const sortedSources = getSortedSources(platform);
    const oldIndex = sortedSources.findIndex((s) => s.id === active.id);
    const newIndex = sortedSources.findIndex((s) => s.id === over.id);

    if (oldIndex === -1 || newIndex === -1) return;

    // Reorder the sources array
    const reorderedSources = arrayMove(sortedSources, oldIndex, newIndex);

    // Update priorities based on new order (1, 2, 3, ...)
    const updatedSources = reorderedSources.map((source, index) => ({
      ...source,
      priority: index + 1,
    }));

    // Update config with new order
    if (!config) return;
    const next = {
      ...config,
      platforms: {
        ...config.platforms,
        [platform]: {
          ...config.platforms[platform],
          sources: updatedSources.map(({ priority: _priority, displayName: _displayName, dbId: _dbId, ...source }) => source),
        },
      },
    };
    setConfig(next);
    setDirty(true);

    // Update priorities in database - PRESERVE existing settings by merging
    const updates = updatedSources
      .filter((source) => source.dbId)
      .map((source) => {
        // Find the current source in dbSources to get all existing settings
        const currentDbSource = dbSources.find(s => s.id === source.dbId);
        if (!currentDbSource) {
          // No existing settings, just set priority
          return apiService.updateSourceSettings(source.dbId!, { priority: source.priority });
        }
        
        // Merge existing settings with new priority (preserve display_name, fetch_delay_seconds, etc.)
        const mergedSettings = {
          ...currentDbSource.settings,
          priority: source.priority
        };
        
        return apiService.updateSourceSettings(source.dbId!, mergedSettings);
      });

    try {
      await Promise.all(updates);
      // Reload database sources to get updated priorities
      const res = await apiService.getSourcesWithSettings();
      if (res.success) {
        setDbSources(res.sources);
      }
      toast.success(`Reordered sources by priority`);
    } catch (_error) {
      toast.error('Failed to update priorities');
    }
  };

  const updateSource = (platform: PlatformKey, index: number, value: string) => {
    if (!config) return;
    const list = [...config.platforms[platform].sources];
    list[index] = { id: value, state: list[index].state};
    const next = {
      ...config,
      platforms: {
        ...config.platforms,
        [platform]: {
          ...config.platforms[platform],
          sources: list,
        },
      },
    };
    setConfig(next);
    setDirty(true);
  };

  const removeSource = (platform: PlatformKey, index: number) => {
    if (!config) return;
    const list = config.platforms[platform].sources.filter((_, i) => i !== index);
    const next = {
      ...config,
      platforms: {
        ...config.platforms,
        [platform]: {
          ...config.platforms[platform],
          sources: list,
        },
      },
    };
    setConfig(next);
    setDirty(true);
  };

  const onSave = async () => {
    if (!config) return;
    setSaving(true);
    const res = await apiService.updateSources(config);
    
    if (res.success) {
      // Reload database sources to get updated list with settings
      const dbSourcesRes = await apiService.getSourcesWithSettings();
      if (dbSourcesRes.success) {
        setDbSources(dbSourcesRes.sources);
      }
      
      toast.success('Sources configuration saved');
      setDirty(false);
    } else {
      toast.error(res.error || 'Failed to save configuration');
    }
    
    setSaving(false);
  };

  function getSourceStateStyle(state: SourceState): string {
    switch (state) {
      case 'enabled': return 'bg-green-100 text-green-700 border-green-200';
      case 'disabled': return 'bg-red-100 text-red-700 border-red-200';  
      default: return 'bg-gray-100 text-gray-700 border-gray-200';
    }
  }

  function cycleSourceState(currentState: SourceState): SourceState {
    // Only toggle between enabled and disabled
    return currentState === 'enabled' ? 'disabled' : 'enabled';
  }

  const toggleSourceState = (platform: PlatformKey, index: number) => {
    if (!config) return;
    
    const currentSources = [...config.platforms[platform].sources];
    const currentState = currentSources[index].state;
    const newState = cycleSourceState(currentState);
    
    // Update the clicked source
    currentSources[index] = { 
      ...currentSources[index], 
      state: newState 
    };
    
    const next = {
      ...config,
      platforms: {
        ...config.platforms,
        [platform]: {
          ...config.platforms[platform],
          sources: currentSources,
        },
      },
    };
    
    setConfig(next);
    setDirty(true);
  };

  if (typeof window !== 'undefined') {
    (window as any).__normalizeSources = normalizeSources;
    (window as any).__denormalizeSources = denormalizeSources;
  }

  if (loading) {
    return (
      <div className={`flex ${embedded ? 'h-48' : 'h-screen'} items-center justify-center text-gray-600`}>
        <Loader2 className="w-5 h-5 mr-2 animate-spin" /> Loading configuration...
      </div>
    );
  }

  if (!config) {
    return (
      <div className={`flex ${embedded ? 'h-48' : 'h-screen'} items-center justify-center text-red-600`}>
        Failed to load configuration
      </div>
    );
  }

  return (
    <div className={embedded ? "bg-gray-100" : "min-h-screen bg-gray-100"}>
      <div className={embedded ? "max-w-5xl mx-auto p-6" : "max-w-5xl mx-auto p-8"}>
        {/* Back link (hidden when embedded) */}
  {!embedded && (
          <div className="mb-3">
            <button
              type="button"
              onClick={() => navigate('/briefing')}
              className="inline-flex items-center text-sm text-gray-600 hover:text-gray-900 transition-colors"
            >
              <ChevronLeft className="w-4 h-4 mr-1" /> Back to Briefing
            </button>
          </div>
        )}

        {/* Title and Save */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Sources Configuration</h1>
          <button
            onClick={onSave}
            disabled={!dirty || saving}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 shadow-sm"
          >
            {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
            Save
          </button>
        </div>

        {/* Global Actions and Counters */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                if (!config) return;
                const next = { ...config, platforms: { ...config.platforms } } as SourceConfig;
                (Object.keys(next.platforms) as string[]).forEach((p) => {
                  next.platforms[p].enabled = true;
                });
                setConfig(next);
                setDirty(true);
              }}
              className="px-3 py-1.5 text-sm rounded-md border border-gray-300 bg-white hover:bg-gray-50"
            >
              Enable All
            </button>
            <button
              onClick={() => {
                if (!config) return;
                const next = { ...config, platforms: { ...config.platforms } } as SourceConfig;
                (Object.keys(next.platforms) as string[]).forEach((p) => {
                  next.platforms[p].enabled = false;
                });
                setConfig(next);
                setDirty(true);
              }}
              className="px-3 py-1.5 text-sm rounded-md border border-gray-300 bg-white hover:bg-gray-50"
            >
              Disable All
            </button>
          </div>
          
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-2 text-sm text-gray-700">
              All:
              <strong className="text-gray-900 text-base">{totalSources}</strong>
            </span>
            <span className="inline-flex items-center gap-2 text-sm text-green-700">
              Enabled:
              <strong className="text-green-900 text-base">{enabledSourcesCount}</strong>
            </span>
          </div>
        </div>

        {/* Platform Dock (macOS-like) */}
        <div className="flex justify-center mb-4">
      <div className="flex items-center gap-3 px-4 py-2 rounded-2xl bg-white/80 backdrop-blur border border-gray-200 shadow-md">
            {platforms.map((platform) => {
              const enabled = config.platforms[platform].enabled;
              const ringClass = enabled ? 'ring ring-green-400 bg-green-50' : 'ring ring-gray-200 bg-gray-50';
        const pulseClass = '';
              return (
                <button
                  key={`dock-${platform}`}
                  onClick={() => {
                    // Expand and persist
                    const next = { ...expanded, [platform]: true };
                    setExpanded(next);
                    saveExpanded(next);
                    // Scroll to card
                    const el = document.getElementById(`platform-${platform}`);
                    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                  }}
          className={`relative h-10 w-10 rounded-xl flex items-center justify-center ${ringClass} ${pulseClass} shadow-sm hover:shadow-lg transition-shadow duration-150`}
                  title={String(platform)}
                >
                  <span className={`${enabled ? 'text-green-700' : 'text-gray-600'}`}>
                    {platformIcon[platform] || <MessageSquare className="w-5 h-5" />}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Platforms */}
        <div className="space-y-6">
          {platforms.map((platform) => (
            <div key={platform} id={`platform-${platform}`} className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div
                role="button"
                tabIndex={0}
                aria-expanded={!!expanded[platform]}
                onClick={() => setExpanded((prev) => { const next = { ...prev, [platform]: !prev[platform] }; saveExpanded(next); return next; })}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setExpanded((prev) => { const next = { ...prev, [platform]: !prev[platform] }; saveExpanded(next); return next; });
                  }
                }}
                className={`flex items-center justify-between p-4 border-b border-gray-200 transition-colors hover:bg-gray-50 ${expanded[platform] ? 'bg-gray-50' : ''}`}
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-md bg-gray-100 text-gray-700 flex items-center justify-center">
                    {platformIcon[platform] || <MessageSquare className="w-5 h-5" />}
                  </div>
                  <h3 className="font-semibold text-gray-900 text-lg capitalize">{platform}</h3>
                </div>
                <div className="flex items-center gap-2">
                  {/* Export removed per request */}
                  <button
                    onClick={(e) => { 
                      e.stopPropagation(); 
                      const sourceIds = config.platforms[platform].sources.map(s => s.id);
                      setBulkEdit({ platform: String(platform), text: sourceIds.join('\n') }); 
                    }}
                    className="inline-flex items-center gap-1 px-2 py-1.5 rounded-md text-sm border border-gray-300 hover:bg-gray-50"
                    title="Bulk edit sources"
                  >
                    <FileText className="w-4 h-4" />
                    Bulk Edit
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); togglePlatform(platform); }}
                    className={`inline-flex items-center px-3 py-1.5 rounded-full text-sm border ${
                      config.platforms[platform].enabled
                        ? 'bg-green-50 text-green-700 border-green-300'
                        : 'bg-gray-50 text-gray-700 border-gray-300'
                    }`}
                  >
                    {config.platforms[platform].enabled ? 'Enabled' : 'Disabled'}
                  </button>
                </div>
              </div>

              {expanded[platform] && (
                <div className="p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-sm font-medium text-gray-900">Sources</h4>
                    <button
                      onClick={() => addSource(platform)}
                      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md border border-gray-300 text-sm hover:bg-gray-50"
                    >
                      <Plus className="w-4 h-4" /> Add Source
                    </button>
                  </div>

                  {config.platforms[platform].sources.length === 0 ? (
                    <div className="text-xs text-gray-500">No sources added yet.</div>
                  ) : (
                    <DndContext
                      sensors={sensors}
                      collisionDetection={closestCenter}
                      onDragEnd={(event) => handleDragEnd(event, platform)}
                    >
                      <SortableContext
                        items={getSortedSources(platform).map((s) => s.id)}
                        strategy={verticalListSortingStrategy}
                      >
                        <div className="space-y-2">
                          {getSortedSources(platform).map((source) => {
                            const originalIndex = config.platforms[platform].sources.findIndex(
                              (s) => s.id === source.id
                            );
                            
                            return (
                              <SortableSourceItem
                                key={source.id}
                                source={source}
                                onToggleState={() => toggleSourceState(platform, originalIndex)}
                                onUpdate={(value) => updateSource(platform, originalIndex, value)}
                                onRemove={() => removeSource(platform, originalIndex)}
                                onSettingsClick={() => handleSettingsClick(platform, source.id)}
                                hasDbSource={!!findDbSource(platform, source.id)}
                                getStateStyle={getSourceStateStyle}
                              />
                            );
                          })}
                        </div>
                      </SortableContext>
                    </DndContext>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      {/* Bulk Editor Modal */}
      {bulkEdit && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white w-full max-w-2xl rounded-lg border border-gray-200 shadow-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-gray-900">Bulk Edit – {bulkEdit.platform}</h3>
              <button className="text-gray-600 hover:text-gray-900" onClick={() => setBulkEdit(null)}>✕</button>
            </div>
            <textarea
              className="w-full h-64 border border-gray-300 rounded-md p-3 font-mono text-sm"
              value={bulkEdit.text}
              onChange={(e) => setBulkEdit({ ...bulkEdit, text: e.target.value })}
              placeholder="One source per line"
            />
            <div className="mt-3 flex items-center justify-end gap-2">
              <button className="px-3 py-1.5 rounded-md border border-gray-300" onClick={() => setBulkEdit(null)}>Cancel</button>
              <button
                className="px-3 py-1.5 rounded-md bg-indigo-600 text-white"
                onClick={() => {
                  if (!config) return;
                  const lines = bulkEdit.text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
                  const sourceItems = lines.map(line => ({ id: line, state: 'enabled' as SourceState }));
                  const next = { ...config, platforms: { ...config.platforms } } as SourceConfig;
                  next.platforms[bulkEdit.platform].sources = sourceItems;
                  setConfig(next);
                  setDirty(true);
                  setBulkEdit(null);
                  toast.success('Sources updated');
                }}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Settings Editor Modal */}
      {editingSource && (
        <SourceSettingsEditor
          source={editingSource}
          onClose={() => setEditingSource(null)}
          onSave={handleSettingsSaved}
        />
      )}
    </div>
  );

  
}


