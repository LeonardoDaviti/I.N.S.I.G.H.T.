import { Suspense } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { Page, PageHeader } from '../components/ui';
import BackLink from '../components/ui/BackLink';
import { LoadingState } from '../components/states';
import { findPost, POSTS, type BlogPost } from '../blog/posts';

const dateLabel = (iso: string) =>
  new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(`${iso}T00:00:00`));

function Meta({ post }: { post: BlogPost }) {
  return (
    <span className="tabular-nums">
      <time dateTime={post.date}>{dateLabel(post.date)}</time> · {post.readingMinutes} min read
    </span>
  );
}

/** `/blog`: the list of posts, newest first. */
function BlogIndex() {
  return (
    <Page width="reading">
      <PageHeader title="Blog" meta="How INSIGHT is built, and what we learn building it" />
      <ul className="space-y-2">
        {POSTS.map((post) => (
          <li key={post.slug}>
            <Link
              to={`/blog/${post.slug}`}
              className="block rounded-md border border-line bg-surface px-4 py-3 transition-[border-color] duration-[120ms] hover:border-line-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg"
            >
              <span className="block text-[0.8125rem] text-fg-3"><Meta post={post} /></span>
              <span className="mt-1 block text-[1.0625rem] font-semibold leading-[1.35] text-fg">{post.title}</span>
              <span className="mt-1 block text-[0.9375rem] leading-[1.55] text-fg-2">{post.summary}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Page>
  );
}

/** `/blog/:slug`: one post in the reading column. An unknown slug goes back to the list. */
function BlogArticle({ post }: { post: BlogPost }) {
  const { Body } = post;
  return (
    <Page width="reading">
      <BackLink to="/blog" label="blog" />
      <article>
        <header className="mb-8">
          <p className="text-[0.8125rem] text-fg-3"><Meta post={post} /></p>
          <h1 className="mt-2 text-[1.75rem] font-[650] leading-[1.15] tracking-[-0.025em] text-fg">{post.title}</h1>
        </header>
        <Suspense fallback={<LoadingState label="Loading post" rows={6} />}>
          <Body />
        </Suspense>
      </article>
    </Page>
  );
}

export default function BlogPage() {
  const { slug } = useParams();
  if (slug === undefined) return <BlogIndex />;
  const post = findPost(slug);
  return post ? <BlogArticle post={post} /> : <Navigate to="/blog" replace />;
}
