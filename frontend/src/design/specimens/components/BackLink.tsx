import BackLink from '../../../components/ui/BackLink';
import { Variant, Variants } from '../parts';

/** The one way out of a detail page, as a link and as a history-back button. */
export default function BackLinkSpecimen() {
  return (
    <Variants>
      <Variant label="to · a router link">
        <BackLink label="components" to="/design/components" className="mb-0 ml-0" />
      </Variant>
      <Variant label="onClick · history back">
        <BackLink label="feed" onClick={() => undefined} className="mb-0 ml-0" />
      </Variant>
    </Variants>
  );
}
