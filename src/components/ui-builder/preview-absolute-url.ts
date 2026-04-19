import { getApiOriginFromV1Base, getApiV1Base } from '@/lib/api-v1-base'

/** Turn `/api/v1/generated-uis/…/serve` (or absolute URLs) into a browser-openable origin URL. */
export function previewAbsoluteUrl(htmlPreviewUrl: string): string {
  if (htmlPreviewUrl.startsWith('http://') || htmlPreviewUrl.startsWith('https://')) {
    return htmlPreviewUrl
  }
  const origin = getApiOriginFromV1Base(getApiV1Base())
  const path = htmlPreviewUrl.startsWith('/') ? htmlPreviewUrl : `/${htmlPreviewUrl}`
  return `${origin}${path}`
}
