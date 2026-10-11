import Row from '../../../components/ui/Row';
import StatusGlyph from '../../../components/ui/StatusGlyph';
import { Variant, Variants } from '../parts';

/** The smol-style row: static, linked, muted (read), with trailing status, and a title that clamps. */
export default function RowSpecimen() {
  return (
    <Variants className="sm:grid-cols-1">
      <Variant label="to · a router link" wide>
        <div className="w-full"><Row meta="Oct 10" title="A new feature for my blog" description="Simon Willison" to="/design/components/Row" /></div>
      </Variant>
      <Variant label="muted · read" wide>
        <div className="w-full"><Row meta="Oct 9" title="An older post you have read" muted /></div>
      </Variant>
      <Variant label="trailing status" wide>
        <div className="w-full"><Row meta="14:20" title="Hacker News" trailing={<StatusGlyph status="failing" />} /></div>
      </Variant>
      <Variant label="worst · the title clamps at two lines" wide>
        <div className="w-full">
          <Row
            meta="Oct 10"
            title="An extraordinarily long title that keeps going well past the width of the column so that it has to wrap and then clamp at the second line instead of pushing the row taller and taller"
          />
        </div>
      </Variant>
    </Variants>
  );
}
