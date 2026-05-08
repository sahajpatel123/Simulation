import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import api from '@/lib/api'
import type { Assumption } from '@/types'

type AssumptionListResponse = {
  project_id: number
  assumptions: Array<Assumption & { impact_score?: number; is_hidden?: boolean }>
}

const normalizeAssumption = (assumption: Assumption & { impact_score?: number; is_hidden?: boolean }): Assumption => ({
  ...assumption,
  impactScore: assumption.impactScore ?? assumption.impact_score ?? 0,
  isHidden: assumption.isHidden ?? assumption.is_hidden ?? false,
})

export const useAssumptions = (projectId: number | string | null) =>
  useQuery<Assumption[]>({
    queryKey: ['assumptions', projectId],
    queryFn: async () => {
      const response = await api.get<Assumption[] | AssumptionListResponse>(`/projects/${projectId}/assumptions`)
      if (Array.isArray(response.data)) return response.data.map(normalizeAssumption)
      return (response.data.assumptions ?? []).map(normalizeAssumption)
    },
    enabled: !!projectId,
    refetchInterval: (data) => {
      // If no assumptions yet, poll faster to catch the results of an extraction
      if (!data || data.length === 0) return 3000
      return 10000 // Otherwise poll every 10s
    },
  })

export const useExtractAssumptions = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (projectId: number) => api.post(`/projects/${projectId}/extract-assumptions`).then((r) => r.data),
    onSuccess: (_, projectId) => {
      qc.invalidateQueries({ queryKey: ['assumptions', projectId] })
      qc.invalidateQueries({ queryKey: ['project', projectId] })
    },
  })
}

export const useUpdateAssumption = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      assumptionId,
      data,
    }: {
      projectId: number
      assumptionId: number
      data: Partial<Assumption>
    }) => api.patch(`/projects/${projectId}/assumptions/${assumptionId}`, data).then((r) => r.data),
    onSuccess: (_, { projectId }) => qc.invalidateQueries({ queryKey: ['assumptions', projectId] }),
  })
}
