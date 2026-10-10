import type { Post } from '../../services/api';

/** What GET /api/posts/item/{id} returns about a post's media (backend `post_media`). */
export interface PostImage {
  url: string;
}

export interface PostVideo {
  provider: 'youtube';
  id: string;
}

export interface PostMedia {
  images: PostImage[];
  video: PostVideo | null;
}

type PostWithMedia = Post & { images?: unknown; video?: unknown };

function isImage(value: unknown): value is PostImage {
  return Boolean(value) && typeof (value as PostImage).url === 'string' && (value as PostImage).url.length > 0;
}

function isVideo(value: unknown): value is PostVideo {
  const video = value as PostVideo | null;
  return Boolean(video) && video?.provider === 'youtube' && typeof video.id === 'string' && video.id.length > 0;
}

/** True when the body already embeds this image (HTML escapes `&` in attributes). */
function inBody(body: string, url: string) {
  return Boolean(body) && (body.includes(url) || body.includes(url.replace(/&/g, '&amp;')));
}

/**
 * The post's images and video, tolerant of an older backend (no fields) and of
 * junk. Images the body already shows inline are dropped, so a picture never
 * appears twice: the body places them where the author did.
 */
export function postMedia(post: Post, body = ''): PostMedia {
  const raw = post as PostWithMedia;
  const seen = new Set<string>();
  const images = (Array.isArray(raw.images) ? raw.images : [])
    .filter(isImage)
    .filter((image) => {
      if (seen.has(image.url) || inBody(body, image.url)) return false;
      seen.add(image.url);
      return true;
    });
  return { images, video: isVideo(raw.video) ? raw.video : null };
}
