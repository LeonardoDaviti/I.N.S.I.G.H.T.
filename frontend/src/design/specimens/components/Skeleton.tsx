import Skeleton from '../../../components/ui/Skeleton';
import { Variant, Variants } from '../parts';

/** Placeholder blocks in the raised tone; they pulse only when motion is allowed. */
export default function SkeletonSpecimen() {
  return (
    <Variants>
      <Variant label="a feed row" wide>
        <div className="w-full max-w-md space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </Variant>
    </Variants>
  );
}
