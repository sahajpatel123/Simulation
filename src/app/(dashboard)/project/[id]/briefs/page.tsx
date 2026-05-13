'use client'

import { useParams } from 'next/navigation'
import { useProject } from '@/hooks/useProjects'
import BriefAuthor from '@/components/brief/BriefAuthor'

export default function SoftwareBriefPage() {
  const params = useParams()
  const projectId = params.id as string
  const { data: project, isLoading } = useProject(projectId)

  if (isLoading || !project) {
    return (
      <div
        style={{
          padding: 80,
          fontFamily: 'var(--font-mono), monospace',
          fontSize: 10,
          letterSpacing: '0.22em',
          color: '#888',
        }}
      >
        LOADING THE PROOF...
      </div>
    )
  }

  return <BriefAuthor projectId={projectId} variant="software" dossierTitle={project.title} />
}
