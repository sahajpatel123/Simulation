import { useMutation, useQuery } from '@tanstack/react-query'

import api from '@/lib/api'
import type { ReportPreview } from '@/types'

export const useReportPreview = (projectId: number | null) =>
  useQuery<ReportPreview>({
    queryKey: ['report-preview', projectId],
    queryFn: async () => (await api.get(`/projects/${projectId}/report/preview`)).data,
    enabled: !!projectId,
  })

export const useGenerateReport = () =>
  useMutation({
    mutationFn: async (projectId: number) => {
      const response = await api.post(`/projects/${projectId}/report`, {}, { responseType: 'blob' })
      const blob = new Blob([response.data], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)
      const filename =
        response.headers['content-disposition']?.split('filename=')[1]?.replace(/"/g, '') ||
        `TheCee_Report_${projectId}.pdf`

      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      URL.revokeObjectURL(url)

      return { downloaded: true, filename }
    },
  })
