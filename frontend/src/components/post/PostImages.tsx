import { useState } from 'react';
import type { PostImage } from './media';

/**
 * One post image, full colour. The feed gives no dimensions, so the frame is
 * reserved at 16:10 before the file arrives and keeps that ratio after: the
 * picture is contained in it, never cropped, and the text below never moves
 * (no layout shift while reading). A dead link removes the frame entirely.
 */
export function PostFigure({ image, alt = '', className = '' }: { image: PostImage; alt?: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <figure
      data-post-image
      className={`relative w-full overflow-hidden rounded-md border border-line bg-raised ${className}`}
      style={{ aspectRatio: '16 / 10' }}
    >
      <img
        src={image.url}
        alt={alt}
        width={1600}
        height={1000}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className="absolute inset-0 h-full w-full object-contain"
      />
    </figure>
  );
}

/** The images after the body: one per row in the reading column. */
export function PostImageList({ images }: { images: PostImage[] }) {
  if (!images.length) return null;
  return (
    <section aria-label="Images" className="mt-12 space-y-6">
      {images.map((image) => (
        <PostFigure key={image.url} image={image} />
      ))}
    </section>
  );
}
