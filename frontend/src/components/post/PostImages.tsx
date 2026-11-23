import { useState } from 'react';
import { proxiedImage } from '../../lib/mediaProxy';
import type { PostImage } from './media';

/** One post image, full colour, in a frame reserved at 16:10 before the file arrives (contained, never cropped), so
 *  the text never shifts; a dead link removes the frame. */
export function PostFigure({ image, postId, alt = '', className = '' }: { image: PostImage; postId?: string; alt?: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <figure
      data-post-image
      className={`relative w-full overflow-hidden rounded-md border border-line bg-raised ${className}`}
      style={{ aspectRatio: '16 / 10' }}
    >
      <img
        src={proxiedImage(postId, image.url)}
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
export function PostImageList({ images, postId }: { images: PostImage[]; postId?: string }) {
  if (!images.length) return null;
  return (
    <section aria-label="Images" className="mt-12 space-y-6">
      {images.map((image) => (
        <PostFigure key={image.url} image={image} postId={postId} />
      ))}
    </section>
  );
}
