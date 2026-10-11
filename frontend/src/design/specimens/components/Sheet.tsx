import Button from '../../../components/ui/Button';
import { Field, Input } from '../../../components/ui/Input';
import { Sheet, SheetContent, SheetTrigger } from '../../../components/ui/Sheet';
import { Variant, Variants } from '../parts';

/** A side sheet for a parallel task: in from the right and out the same way. */
export default function SheetSpecimen() {
  return (
    <Variants>
      <Variant label="from the right · 260ms in, 200ms out">
        <Sheet>
          <SheetTrigger asChild><Button>Open sheet</Button></SheetTrigger>
          <SheetContent title="Simon Willison" description="rss · hourly">
            <Field label="Name" htmlFor="specimen-sheet-name">
              <Input id="specimen-sheet-name" defaultValue="Simon Willison" />
            </Field>
          </SheetContent>
        </Sheet>
      </Variant>
    </Variants>
  );
}
