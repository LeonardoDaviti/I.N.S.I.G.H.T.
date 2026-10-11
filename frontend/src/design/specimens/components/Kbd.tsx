import Kbd from '../../../components/ui/Kbd';
import { Variant, Variants } from '../parts';

/** Key caps as the help dialog and the top bar show them. */
export default function KbdSpecimen() {
  return (
    <Variants>
      <Variant label="single keys">
        <Kbd>j</Kbd><Kbd>k</Kbd><Kbd>o</Kbd><Kbd>?</Kbd><Kbd>esc</Kbd>
      </Variant>
      <Variant label="a chord">
        <span className="inline-flex gap-1"><Kbd>⌘</Kbd><Kbd>K</Kbd></span>
        <span className="inline-flex gap-1"><Kbd>Ctrl</Kbd><Kbd>K</Kbd></span>
      </Variant>
    </Variants>
  );
}
