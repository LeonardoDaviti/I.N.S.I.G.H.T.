/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The build stamp (issue 0020): VERSION's contents, the short commit and its date (YYYY-MM-DD). */
  readonly VITE_INSIGHT_VERSION?: string;
  readonly VITE_INSIGHT_COMMIT?: string;
  readonly VITE_INSIGHT_COMMIT_DATE?: string;
}
