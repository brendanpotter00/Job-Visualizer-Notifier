import { useEffect } from 'react';

/**
 * Set the title and meta description imperatively (a React 19 hoisted `<title>`
 * lands after index.html's static one, and the first wins); restore on unmount.
 */
export function useDocumentHead(title: string, description: string): void {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = title;

    const existing = document.head.querySelector<HTMLMetaElement>('meta[name="description"]');
    const previousDescription = existing?.getAttribute('content') ?? null;
    let created: HTMLMetaElement | null = null;
    if (existing) {
      existing.setAttribute('content', description);
    } else {
      created = document.createElement('meta');
      created.name = 'description';
      created.content = description;
      document.head.appendChild(created);
    }

    return () => {
      document.title = previousTitle;
      if (created) {
        created.remove();
      } else if (existing && previousDescription !== null) {
        existing.setAttribute('content', previousDescription);
      }
    };
  }, [title, description]);
}
