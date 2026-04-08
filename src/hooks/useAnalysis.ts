import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import api from '@/lib/api'
import type { CompetitiveAnalysis, Interventions, Premortem } from '@/types'

export const usePremortem = (projectId: number | null) =>
  useQuery<Premortem>({
    queryKey: ['premortem', projectId],
    queryFn: async () => (await api.get(`/projects/${projectId}/premortem`)).data,
    enabled: !!projectId,
    retry: (count, err: unknown) => {
      const status = (err as { response?: { status: number } })?.response?.status
      return status !== 404 && count < 1
    },
  })

export const useRunPremortem = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (projectId: number) => api.post(`/projects/${projectId}/premortem`).then((r) => r.data),
    onSuccess: (_, projectId) => qc.invalidateQueries({ queryKey: ['premortem', projectId] }),
  })
}

export const useInterventions = (projectId: number | null) =>
  useQuery<Interventions>({
    queryKey: ['interventions', projectId],
    queryFn: async () => (await api.get(`/projects/${projectId}/interventions`)).data,
    enabled: !!projectId,
    retry: (count, err: unknown) => {
      const status = (err as { response?: { status: number } })?.response?.status
      return status !== 404 && count < 1
    },
  })

export const useGenerateInterventions = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (projectId: number) => api.post(`/projects/${projectId}/interventions`).then((r) => r.data),
    onSuccess: (_, projectId) => qc.invalidateQueries({ queryKey: ['interventions', projectId] }),
  })
}

export const useCompetitiveAnalysis = (projectId: number | null) =>
  useQuery<CompetitiveAnalysis>({
    queryKey: ['competitive', projectId],
    queryFn: async () => (await api.get(`/projects/${projectId}/competitive-analysis`)).data,
    enabled: !!projectId,
    retry: (count, err: unknown) => {
      const status = (err as { response?: { status: number } })?.response?.status
      return status !== 404 && count < 1
    },
  })

export const useRunCompetitiveAnalysis = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (projectId: number) =>
      api.post(`/projects/${projectId}/competitive-analysis`).then((r) => r.data),
    onSuccess: (_, projectId) => qc.invalidateQueries({ queryKey: ['competitive', projectId] }),
  })
}

export const useStressTest = (projectId: number | null) =>
  useQuery({
    queryKey: ['stress-test', projectId],
    queryFn: async () => (await api.get(`/projects/${projectId}/stress-test`)).data,
    enabled: !!projectId,
    retry: (count, err: unknown) => {
      const status = (err as { response?: { status: number } })?.response?.status
      return status !== 404 && count < 1
    },
  })

export const useRunStressTest = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (projectId: number) => api.post(`/projects/${projectId}/stress-test`).then((r) => r.data),
    onSuccess: (_, projectId) => qc.invalidateQueries({ queryKey: ['stress-test', projectId] }),
  })
}
