import { useEffect } from 'react';

import { useScopeVoice } from '../../hooks/useVoice';
import VoiceHeader from './VoiceHeader';

/**
 * The reader's voice header (issue 0132 A), loaded in its own chunk: on a voice's page that voice, on a channel's
 * page the voice it is a channel of (nothing when none). `onName` gives the reader the voice's name for its title.
 */
export default function ScopeVoiceHeader({ scope, onName }: { scope: string; onName?: (name: string | null) => void }) {
  const voice = useScopeVoice(scope);
  const name = scope.startsWith('voice:') ? voice?.name ?? null : null;
  useEffect(() => {
    onName?.(name);
  }, [name, onName]);
  return voice ? <VoiceHeader scope={scope} voice={voice} /> : null;
}
