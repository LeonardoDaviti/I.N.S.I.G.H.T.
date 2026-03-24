import { useState } from 'react';
import { MessageSquare, Rss, Send, Youtube } from 'lucide-react';

import {
  getSourceAvatarModel,
  type SourcePresentationItem,
} from '../lib/sourcePresentation';

type SourceAvatarProps = {
  source: SourcePresentationItem;
  size?: 'sm' | 'md';
  mode?: 'source' | 'platform';
  className?: string;
};

const SIZE_STYLES = {
  sm: {
    frame: 'h-7 w-7 text-[10px]',
    icon: 'h-3.5 w-3.5',
  },
  md: {
    frame: 'h-10 w-10 text-xs',
    icon: 'h-5 w-5',
  },
};

function platformTone(platform: string) {
  switch (platform) {
    case 'reddit':
      return 'border-orange-200 bg-orange-50 text-orange-700';
    case 'rss':
      return 'border-indigo-200 bg-indigo-50 text-indigo-700';
    case 'telegram':
      return 'border-sky-200 bg-sky-50 text-sky-700';
    case 'youtube':
      return 'border-rose-200 bg-rose-50 text-rose-700';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-600';
  }
}

function PlatformGlyph({ platform, className }: { platform: string; className: string }) {
  switch (platform) {
    case 'reddit':
      return <MessageSquare className={className} />;
    case 'rss':
      return <Rss className={className} />;
    case 'telegram':
      return <Send className={className} />;
    case 'youtube':
      return <Youtube className={className} />;
    default:
      return null;
  }
}

export default function SourceAvatar({
  source,
  size = 'sm',
  mode = 'source',
  className = '',
}: SourceAvatarProps) {
  const model = getSourceAvatarModel(source);
  const [imageBroken, setImageBroken] = useState(false);
  const styles = SIZE_STYLES[size];
  const tone = platformTone(model.platformKey);
  const showImage = mode === 'source' && Boolean(model.faviconUrl) && !imageBroken;
  const showGlyph = mode === 'platform';

  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full border font-semibold uppercase tracking-[0.12em] ${styles.frame} ${tone} ${className}`}
      aria-hidden="true"
    >
      {showImage ? (
        <img
          src={model.faviconUrl!}
          alt=""
          className="h-full w-full rounded-full object-cover"
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setImageBroken(true)}
        />
      ) : showGlyph ? (
        <PlatformGlyph platform={model.platformKey} className={styles.icon} />
      ) : (
        model.fallback
      )}
    </span>
  );
}
