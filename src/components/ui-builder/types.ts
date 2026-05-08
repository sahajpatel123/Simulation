export interface GeneratedUI {
  id: number
  version: number
  product_type: string
  html_preview_url: string
  html_content?: string
  pages_detected: string[]
  message?: string
}

export interface UIGenerateRequest {
  prompt: string
  product_type: string
  pages_required: string[]
  target_demographic?: string
  price_point?: string
}

export interface GeneratedUIHistoryRow {
  id: number
  version: number
  product_type: string
  pages_generated?: number
  html_preview_url: string
  html_content?: string
  created_at: string | null
}

export interface GeneratedUIHistoryResponse {
  uis: GeneratedUIHistoryRow[]
}

export interface SimulateUIResponse {
  ui_simulation_run_id: number
  status?: string
  message?: string
}
