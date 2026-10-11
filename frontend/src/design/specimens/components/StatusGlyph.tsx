import StatusGlyph from '../../../components/ui/StatusGlyph';
import { STATUS_LABEL, type Status } from '../../../components/ui/styles';
import { Variant, Variants } from '../parts';

const STATUSES = Object.keys(STATUS_LABEL) as Status[];

/** Every status as glyph plus word, glyph only (word for screen readers), and with a custom word. */
export default function StatusGlyphSpecimen() {
  return (
    <Variants>
      <Variant label="glyph + word" wide>
        {STATUSES.map((status) => <StatusGlyph key={status} status={status} />)}
      </Variant>
      <Variant label="hideLabel · dense rows" wide>
        {STATUSES.map((status) => <StatusGlyph key={status} status={status} hideLabel />)}
      </Variant>
      <Variant label="label · a custom word">
        <StatusGlyph status="due" label="overdue 3d" />
        <StatusGlyph status="backoff" label="backoff · retry 14:20" />
      </Variant>
    </Variants>
  );
}
