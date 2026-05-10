import { getApiOriginFromV1Base, getApiV1Base } from '@/lib/api-v1-base'

/** Turn generated preview paths into browser-openable URLs without double-prefixing API bases. */
export function previewAbsoluteUrl(htmlPreviewUrl: string): string {
  if (htmlPreviewUrl.startsWith('http://') || htmlPreviewUrl.startsWith('https://')) {
    return htmlPreviewUrl
  }

  const path = htmlPreviewUrl.startsWith('/') ? htmlPreviewUrl : `/${htmlPreviewUrl}`
  const apiV1Base = getApiV1Base()
  const pathWithoutApiPrefix = path.replace(/^\/api\/v1(?=\/|$)/, '')

  if (apiV1Base.startsWith('/')) {
    return `${apiV1Base}${pathWithoutApiPrefix}`
  }

  return `${getApiOriginFromV1Base(apiV1Base)}${path}`
}
