export type SddStage = 'proposal' | 'design' | 'tasks' | 'apply' | 'review' | 'archive'

export type SddProposalStatus = 'черновик' | 'согласовано' | 'не указан'

export type SddVerdict = 'пройдено' | 'не пройдено' | 'нет вердикта'

export type SddTasks = { done: number; total: number; next: string | null }

export type SddReview = { round: number | null; verdict: SddVerdict; summary: string }

export type SddChange = {
  id: string
  title: string
  proposal: SddProposalStatus | null
  hasDesign: boolean
  tasks: SddTasks | null
  review: SddReview | null
  stage: SddStage
  nextStep: string
  nextSkill: string | null
  updatedAt: number
}

export type SddBoard = {
  hasSdd: boolean
  changes: SddChange[]
  archived: string[]
}

declare module 'claude-code' {
  interface PluginState {
    'sdd-board': { board: SddBoard | null }
  }
}
