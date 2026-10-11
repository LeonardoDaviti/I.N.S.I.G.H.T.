import { Link } from 'react-router-dom';
import { Star } from 'lucide-react';
import Button from '../../../components/ui/Button';
import { Variant, Variants } from '../parts';

/** The one button: four variants, four sizes, disabled, and as a router link. */
export default function ButtonSpecimen() {
  return (
    <Variants>
      <Variant label="variant">
        <Button variant="primary">Primary</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="ghost">Ghost</Button>
      </Variant>
      <Variant label="danger · behind a ConfirmDialog">
        <Button variant="danger">Delete source</Button>
      </Variant>
      <Variant label="size sm · md · lg">
        <Button size="sm">Small</Button>
        <Button size="md">Medium</Button>
        <Button size="lg">Large</Button>
      </Variant>
      <Variant label="icon · named by aria-label">
        <Button size="icon" variant="ghost" aria-label="Star"><Star aria-hidden="true" /></Button>
        <Button size="icon" aria-label="Star (outline)"><Star aria-hidden="true" /></Button>
      </Variant>
      <Variant label="disabled">
        <Button variant="primary" disabled>Primary</Button>
        <Button variant="secondary" disabled>Secondary</Button>
      </Variant>
      <Variant label="asChild · a router link">
        <Button asChild variant="secondary"><Link to="/design/components">All components</Link></Button>
      </Variant>
    </Variants>
  );
}
