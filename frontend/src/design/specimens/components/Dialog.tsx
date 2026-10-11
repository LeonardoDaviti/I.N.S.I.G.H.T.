import Button from '../../../components/ui/Button';
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogTrigger } from '../../../components/ui/Dialog';
import { Variant, Variants } from '../parts';

/** A centred dialog over a scrim: animated (occasional), and instant (the ⌘K way). */
export default function DialogSpecimen() {
  return (
    <Variants>
      <Variant label="default · 200ms in, a fade under reduced motion">
        <Dialog>
          <DialogTrigger asChild><Button>Open dialog</Button></DialogTrigger>
          <DialogContent title="Rename track" description="The name shows in the rail and in ⌘K.">
            <DialogFooter>
              <DialogClose asChild><Button variant="ghost">Cancel</Button></DialogClose>
              <DialogClose asChild><Button variant="primary">Rename</Button></DialogClose>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </Variant>
      <Variant label="instant · opened many times a day">
        <Dialog>
          <DialogTrigger asChild><Button>Open instant dialog</Button></DialogTrigger>
          <DialogContent title="Keyboard shortcuts" instant>
            <p className="mt-3 text-[0.875rem] text-fg-2">No animation in or out (P12).</p>
          </DialogContent>
        </Dialog>
      </Variant>
    </Variants>
  );
}
