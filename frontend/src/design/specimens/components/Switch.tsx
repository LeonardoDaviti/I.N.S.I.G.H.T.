import { useState } from 'react';
import Switch from '../../../components/ui/Switch';
import { Variant, Variants } from '../parts';

/** On, off and disabled; the live one toggles. */
export default function SwitchSpecimen() {
  const [on, setOn] = useState(true);
  return (
    <Variants>
      <Variant label="live">
        <Switch checked={on} onCheckedChange={setOn} aria-label="Fetch hourly" />
        <span className="text-[0.875rem] text-fg-2">{on ? 'on' : 'off'}</span>
      </Variant>
      <Variant label="off · disabled">
        <Switch checked={false} onCheckedChange={() => undefined} aria-label="Off" />
        <Switch checked onCheckedChange={() => undefined} aria-label="Disabled on" disabled />
        <Switch checked={false} onCheckedChange={() => undefined} aria-label="Disabled off" disabled />
      </Variant>
    </Variants>
  );
}
