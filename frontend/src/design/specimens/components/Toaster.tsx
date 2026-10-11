import { toast } from 'sonner';
import Button from '../../../components/ui/Button';
import { Variant, Variants } from '../parts';

/** The app's toaster is mounted once in the shell; these send it the three kinds of toast. */
export default function ToasterSpecimen() {
  return (
    <Variants>
      <Variant label="outcome · with undo · error" wide>
        <Button onClick={() => toast('Marked 12 posts read')}>Plain</Button>
        <Button onClick={() => toast('Source removed', { action: { label: 'Undo', onClick: () => undefined } })}>With undo</Button>
        <Button onClick={() => toast.error('× Could not reach the server. Try again in a minute.')}>Error</Button>
      </Variant>
    </Variants>
  );
}
