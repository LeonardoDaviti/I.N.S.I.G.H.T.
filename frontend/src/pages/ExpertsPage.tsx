import FoldersExpertsPanel from '../components/FoldersExpertsPanel';
import { Page } from '../components/ui';

/** Tracks (`/tracks`, `/experts`): the folders/tracks you read by, and the experts that brief on them. */
export default function ExpertsPage() {
  return (
    <Page width="list">
      <FoldersExpertsPanel />
    </Page>
  );
}
