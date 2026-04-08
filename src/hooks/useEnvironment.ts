import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import api from '@/lib/api'
import type { Environment } from '@/types'

export const useEnvironment = (projectId: number | string | null) =>
  useQuery<Environment>({
    queryKey: ['environment', projectId],
    queryFn: async () => (await api.get(`/projects/${projectId}/environments`)).data,
    enabled: !!projectId,
    retry: (count, err: unknown) => {
      const status = (err as { response?: { status: number } })?.response?.status
      return status !== 404 && count < 2
    },
  })

export const useCreateEnvironment = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      payload,
    }: {
      projectId: number
      payload: {
        mode: string
        manual_params?: Record<string, number>
        scenario_type?: string
      }
    }) => api.post(`/projects/${projectId}/environments`, payload).then((r) => r.data),
    onSuccess: (_, { projectId }) => qc.invalidateQueries({ queryKey: ['environment', projectId] }),
  })
}

export const useScenarioPresets = (projectId: number | null) =>
  useQuery({
    queryKey: ['presets', projectId],
    queryFn: async () => (await api.get(`/projects/${projectId}/environments/presets`)).data,
    enabled: !!projectId,
  })
