import { Field, Input, Select, Textarea } from '../../../components/ui/Input';
import { Variant, Variants } from '../parts';

/** The fields: text, disabled, invalid, a textarea, a native select, and a labelled field with a hint. */
export default function InputSpecimen() {
  return (
    <Variants>
      <Variant label="Input">
        <Input aria-label="Search sources" placeholder="Search sources…" />
      </Variant>
      <Variant label="disabled · invalid">
        <Input aria-label="Disabled" defaultValue="read only" disabled />
        <Input aria-label="Invalid" defaultValue="not a url" aria-invalid="true" />
      </Variant>
      <Variant label="Textarea">
        <Textarea aria-label="Notes" defaultValue="Two lines of text, at the body size and leading." />
      </Variant>
      <Variant label="Select · native">
        <Select aria-label="Cadence" defaultValue="hourly">
          <option value="hourly">hourly</option>
          <option value="daily">daily</option>
        </Select>
      </Variant>
      <Variant label="Field · label and hint" wide>
        <Field label="Feed URL" hint="RSS or Atom; we find the feed from a page URL too." htmlFor="specimen-feed-url" className="w-full max-w-sm">
          <Input id="specimen-feed-url" placeholder="https://simonwillison.net" />
        </Field>
      </Variant>
    </Variants>
  );
}
