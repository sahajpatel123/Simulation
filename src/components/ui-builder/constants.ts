export const PRODUCT_TYPES = [
  'saas',
  'marketplace',
  'mobile_app',
  'developer_tool',
  'enterprise_software',
  'consumer_hardware',
  'health_hardware',
  'iot_hardware',
  'wearable',
  'b2b_hardware',
] as const

export function formatProductTypeLabel(pt: string) {
  return pt.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
