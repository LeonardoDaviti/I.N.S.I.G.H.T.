import TextLink, { ExternalLink } from '../../../components/ui/TextLink';
import { Variant, Variants } from '../parts';

/** Underlined links in the text colour: internal, muted, and external (new tab). */
export default function TextLinkSpecimen() {
  return (
    <Variants>
      <Variant label="TextLink · muted">
        <TextLink to="/design/components">components</TextLink>
        <TextLink to="/design/components" muted>muted</TextLink>
      </Variant>
      <Variant label="ExternalLink · new tab">
        <ExternalLink href="https://news.smol.ai">news.smol.ai</ExternalLink>
      </Variant>
      <Variant label="in a sentence" wide>
        <p className="max-w-reading text-reading text-fg">
          An empty scope points quietly to <TextLink to="/design/pages/sources">Sources</TextLink>, never to a fetch button.
        </p>
      </Variant>
    </Variants>
  );
}
