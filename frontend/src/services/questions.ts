// Questions with citations (issue 0275, Mark X): the reader's question answered only from their own posts, by the
// worker (the page polls while it waits).
import { request } from '../lib/request';

export interface AnswerSentence {
  text: string;
  /** The numbers of the posts it rests on (`posts[].n`). */
  cites: number[];
}

export interface AnswerPost {
  n: number;
  id: string;
  title: string | null;
  url: string | null;
  at: string | null;
  source: string | null;
}

export interface QuestionView {
  id: string;
  q: string;
  status: 'waiting' | 'answered' | 'failed';
  sentences: AnswerSentence[];
  posts: AnswerPost[];
  not_in_sources: boolean;
  dropped: number;
}

const PATH = '/api/markx/questions';

export const questionsApi = {
  on: () => request<{ on: boolean }>(`${PATH}/on`),
  ask: (q: string) => request<QuestionView>(PATH, { method: 'POST', body: { q } }),
  get: (id: string) => request<QuestionView>(`${PATH}/${encodeURIComponent(id)}`),
};
