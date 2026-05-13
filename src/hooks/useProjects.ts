import { useQuery, useQueryClient } from '@tanstack/react-query'

import api from '@/lib/api'
import type { Project } from '@/types'
import { useCeeMutation } from './useMutationFactory'

type ProjectListResponse = { projects: Project[]; total: number }

const normalizeProject = (project: Project): Project => {
  const p = project as unknown as Record<string, unknown>
  const readingsFromApi =
    typeof p.readings_json === "string"
      ? p.readings_json
      : typeof p.readingsJson === "string"
        ? p.readingsJson
        : undefined
  const precisFromApi =
    typeof p.precis === "string" ? p.precis : undefined
  const fingerprintFromApi =
    typeof p.precis_title_fingerprint === "string"
      ? p.precis_title_fingerprint
      : typeof p.precisTitleFingerprint === "string"
        ? p.precisTitleFingerprint
        : undefined
  return {
    ...project,
    readings_json: readingsFromApi ?? project.readings_json,
    precis: precisFromApi ?? project.precis,
    precis_title_fingerprint:
      fingerprintFromApi ?? project.precis_title_fingerprint,
    dossier_axis: project.dossier_axis ?? null,
    created_at:
      project.created_at ??
      (project.createdAt
        ? new Date(project.createdAt).toISOString()
        : undefined),
    updated_at:
      project.updated_at ??
      (project.updatedAt
        ? new Date(project.updatedAt).toISOString()
        : undefined),
  }
}

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
  dossier_axis?: string | null
}

export const useCreateProject = () => {
  const qc = useQueryClient()
  return useCeeMutation(
    (payload: CreateProjectPayload) => {
      const description = payload.description
      const rawTitle = payload.title ?? ''
      const title = rawTitle.trim() || description.trim().slice(0, 500) || 'Untitled idea'
      return api
        .post('/projects', {
          title,
          description,
          intake_mode: payload.intake_mode ?? 'IDEA',
          landing_page_url: payload.landing_page_url,
          mvp_feature_list: payload.mvp_feature_list ?? [],
          existing_product_description: payload.existing_product_description,
          dossier_axis: payload.dossier_axis ?? 'software',
        })
        .then((r) => r.data as Project)
    },
    [['projects']],
    {
      onSuccess: (data) => {
        if (data && typeof data === 'object' && data.id != null) {
          const normalized = normalizeProject(data)
          qc.setQueryData(['project', Number(normalized.id)], normalized)
        }
      },
    }
  )
}

export const useDeleteProject = () =>
  useCeeMutation(
    (id: number) => api.delete(`/projects/${id}`),
    [['projects']]
  )

type UpdateProjectPayload = {
  id: number | string
  title?: string
  description?: string
}

export const useUpdateProject = () => {
  const qc = useQueryClient()
  return useCeeMutation(
    async ({ id, title, description }: UpdateProjectPayload) => {
      const body: { title?: string; description?: string } = {}
      if (title !== undefined) body.title = title
      if (description !== undefined) body.description = description
      if (Object.keys(body).length === 0) {
        throw new Error("updateProject: title or description required")
      }
      const { data } = await api.patch<Project>(`/projects/${id}`, body)
      return data
    },
    [['projects']],
    {
      onSuccess: (data) => {
        const normalized = normalizeProject(data)
        qc.setQueryData(['project', Number(normalized.id)], normalized)
      },
    }
  )
}

/** Alias for rename/patch flows — same behavior as {@link useUpdateProject}. */
export const usePatchProject = useUpdateProject

export const useArchiveProject = () => {
  const qc = useQueryClient()
  return useCeeMutation(
    (id: number) => api.patch<Project>(`/projects/${id}/archive`).then((r) => r.data),
    [['projects']],
    {
      onSuccess: (data) => {
        const normalized = normalizeProject(data)
        qc.setQueryData(['project', Number(normalized.id)], normalized)
      },
    }
  )
}

export const useUnarchiveProject = () => {
  const qc = useQueryClient()
  return useCeeMutation(
    (id: number) => api.patch<Project>(`/projects/${id}/unarchive`).then((r) => r.data),
    [['projects']],
    {
      onSuccess: (data) => {
        const normalized = normalizeProject(data)
        qc.setQueryData(['project', Number(normalized.id)], normalized)
      },
    }
  )
}
