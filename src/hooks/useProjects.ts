import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import api from '@/lib/api'
import type { Project } from '@/types'

type ProjectListResponse = { projects: Project[]; total: number }

const normalizeProject = (project: Project): Project => ({
  ...project,
  created_at: project.created_at ?? (project.createdAt ? new Date(project.createdAt).toISOString() : undefined),
  updated_at: project.updated_at ?? (project.updatedAt ? new Date(project.updatedAt).toISOString() : undefined),
})

export const useProjects = () =>
  useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: async () => {
      const response = await api.get<ProjectListResponse | Project[]>('/projects')
      if (Array.isArray(response.data)) return response.data.map(normalizeProject)
      return (response.data.projects ?? []).map(normalizeProject)
    },
  })

export const useProject = (id: number | string | null) =>
  useQuery<Project>({
    queryKey: ['project', id],
    queryFn: async () => normalizeProject((await api.get(`/projects/${id}`)).data),
    enabled: !!id,
  })

type CreateProjectPayload = {
  title?: string
  description: string
  intake_mode?: 'IDEA' | 'MID_BUILD' | 'PRE_LAUNCH'
  landing_page_url?: string
  mvp_feature_list?: string[]
  existing_product_description?: string
}

export const useCreateProject = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CreateProjectPayload | string) => {
      const description = typeof payload === 'string' ? payload : payload.description
      const raw = typeof payload === 'string' ? ({} as CreateProjectPayload) : payload
      const rawTitle = typeof payload === 'string' ? '' : (payload.title ?? '')
      const title = rawTitle.trim() || description.trim().slice(0, 60) || 'Untitled idea'
      return api
        .post('/projects', {
          title,
          description,
          intake_mode: raw.intake_mode ?? 'IDEA',
          landing_page_url: raw.landing_page_url,
          mvp_feature_list: raw.mvp_feature_list ?? [],
          existing_product_description: raw.existing_product_description,
        })
        .then((r) => r.data)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })
}

export const useDeleteProject = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/projects/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })
}
