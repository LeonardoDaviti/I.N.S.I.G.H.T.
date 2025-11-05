import React, { useState, useRef, useEffect } from 'react';
import { X, Save, AlertCircle } from 'lucide-react';
import { apiService } from '../services/api';
import type { SourceSettings, SourceWithSettings } from '../services/api';

interface SourceSettingsEditorProps {
  source: SourceWithSettings;
  onClose: () => void;
  onSave: () => void;
}

export default function SourceSettingsEditor({ source, onClose, onSave }: SourceSettingsEditorProps) {
  const [settings, setSettings] = useState<SourceSettings>({
    display_name: source.settings.display_name || '',
    fetch_delay_seconds: source.settings.fetch_delay_seconds ?? 1,
    priority: source.settings.priority ?? 999,
    max_posts_per_fetch: source.settings.max_posts_per_fetch ?? 50,
  });
  
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const modalRef = useRef<HTMLDivElement>(null);

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

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);

    try {
      // Only send non-empty display_name, otherwise send null to use default
      const settingsToSave = {
        ...settings,
        display_name: settings.display_name?.trim() || undefined,
      };

      const response = await apiService.updateSourceSettings(source.id, settingsToSave);

      if (response.success) {
        onSave();
        onClose();
      } else {
        setError(response.error || 'Failed to save settings');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error occurred');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div ref={modalRef} className="bg-white rounded-lg shadow-xl max-w-md w-full">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Source Settings</h2>
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
          {/* Source Info */}
          <div className="bg-gray-50 p-3 rounded-md border border-gray-200">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Source</div>
            <div className="text-sm font-medium text-gray-900">{source.handle_or_url}</div>
            <div className="text-xs text-gray-500 mt-1">{source.platform.toUpperCase()}</div>
          </div>

          {/* Display Name */}
          <div>
            <label htmlFor="display_name" className="block text-sm font-medium text-gray-700 mb-1">
              Display Name
            </label>
            <input
              id="display_name"
              type="text"
              value={settings.display_name || ''}
              onChange={(e) => setSettings({ ...settings, display_name: e.target.value })}
              placeholder={source.handle_or_url}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
            />
            <p className="text-xs text-gray-500 mt-1">
              Leave empty to use the default URL/handle
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
              value={settings.fetch_delay_seconds}
              onChange={(e) => setSettings({ ...settings, fetch_delay_seconds: parseInt(e.target.value) || 0 })}
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
              value={settings.priority}
              onChange={(e) => setSettings({ ...settings, priority: parseInt(e.target.value) || 999 })}
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
              value={settings.max_posts_per_fetch}
              onChange={(e) => setSettings({ ...settings, max_posts_per_fetch: parseInt(e.target.value) || 50 })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
              disabled
            />
            <p className="text-xs text-gray-500 mt-1">
              ⚠️ Not enforced (future feature)
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-md">
              <AlertCircle className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 p-4 border-t border-gray-200 bg-gray-50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isSaving ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                Save Settings
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

