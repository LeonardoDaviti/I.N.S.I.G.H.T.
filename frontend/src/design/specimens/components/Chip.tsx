import { useState } from 'react';
import { Chip, FilterChip } from '../../../components/ui/Chip';
import { Variant, Variants } from '../parts';

/** Static chips in their four looks, and filter chips that toggle, with counts. */
export default function ChipSpecimen() {
  const [selected, setSelected] = useState('failing');
  return (
    <Variants>
      <Variant label="Chip · outline · solid · quiet · dashed">
        <Chip>rss</Chip>
        <Chip variant="solid">failing</Chip>
        <Chip variant="quiet">telegram</Chip>
        <Chip variant="dashed">backoff</Chip>
      </Variant>
      <Variant label="FilterChip · selected is the inverted block">
        {[['all', 12847], ['failing', 3], ['due', 0]].map(([name, count]) => (
          <FilterChip key={name} selected={selected === name} count={Number(count)} onClick={() => setSelected(String(name))}>
            {name}
          </FilterChip>
        ))}
      </Variant>
      <Variant label="worst · a long label stays one line" wide>
        <Chip className="max-w-[14rem] truncate">a-very-long-platform-name-that-does-not-stop</Chip>
      </Variant>
    </Variants>
  );
}
