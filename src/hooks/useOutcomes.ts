import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import api from '@/lib/api'
import type { OutcomeRecord } from '@/types'

export interface OutcomeHistory {
  project_id: number
  outcomes: OutcomeRecord[]
  total: number
  average_calibration_score: number
  best_calibration_score: number
  worst_calibration_score: number
  calibration_trend: string
}

export const useOutcomes = (projectId: number | null) =>
  useQuery<OutcomeHistory>({
    queryKey: ['outcomes', projectId],
    queryFn: async () => (await api.get(`/projects/${projectId}/outcomes`)).data,
    enabled: !!projectId,
  })

export const useRecordOutcome = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      payload,
    }: {
      projectId: number
      payload: {
        actual_conversion_rate: number
        actual_mrr: number
        actual_cac: number
        actual_churn_rate: number
        days_since_launch?: number
        notes?: string
      }
    }) => api.post(`/projects/${projectId}/outcomes`, payload).then((r) => r.data),
    onSuccess: (_, { projectId }) => qc.invalidateQueries({ queryKey: ['outcomes', projectId] }),
  })
}
