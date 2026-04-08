import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import api, { apiLong } from '@/lib/api'
import type { SimulationResult, SimulationStatusResponse } from '@/types'

export const useSimulations = (projectId: number | string | null) =>
  useQuery<SimulationStatusResponse[]>({
    queryKey: ['simulations', projectId],
    queryFn: async () => (await api.get(`/simulations/project/${projectId}`)).data,
    enabled: !!projectId,
  })

export const useSimulationStatus = (simulationId: number | null, pollingMs: number = 2000) =>
  useQuery<SimulationStatusResponse>({
    queryKey: ['simulation-status', simulationId],
    queryFn: async () => (await api.get(`/simulations/${simulationId}/status`)).data,
    enabled: !!simulationId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'COMPLETED' || status === 'FAILED') return false
      return pollingMs
    },
  })

export const useSimulationResults = (simulationId: number | null) =>
  useQuery<SimulationResult>({
    queryKey: ['simulation-results', simulationId],
    queryFn: async () => (await api.get(`/simulations/${simulationId}/results`)).data,
    enabled: !!simulationId,
    retry: (count, err: unknown) => {
      const status = (err as { response?: { status: number } })?.response?.status
      return status !== 409 && count < 1
    },
  })

export const useCreateSimulation = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      consumerVolume = 10000,
    }: {
      projectId: number
      consumerVolume?: number
    }) =>
      apiLong
        .post('/simulations', {
          project_id: projectId,
          consumer_volume: consumerVolume,
        })
        .then((r) => r.data),
    onSuccess: (data: { project_id?: number; projectId?: number }) => {
      const id = data.project_id ?? data.projectId
      if (id) qc.invalidateQueries({ queryKey: ['simulations', id] })
    },
  })
}

export const useSimulationProgress = (simulationId: number | null) =>
  useQuery({
    queryKey: ['simulation-progress', simulationId],
    queryFn: async () => (await api.get(`/simulations/${simulationId}/progress`)).data,
    enabled: !!simulationId,
    refetchInterval: 2000,
  })
