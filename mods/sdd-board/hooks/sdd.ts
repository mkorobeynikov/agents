import type { EngineInterface } from 'claude-code'

import type {
  SddBoard,
  SddChange,
  SddProposalStatus,
  SddReview,
  SddStage,
  SddTasks,
} from '../types'

export const STAGES: { stage: SddStage; label: string }[] = [
  { stage: 'proposal', label: 'proposal' },
  { stage: 'design', label: 'design' },
  { stage: 'tasks', label: 'tasks' },
  { stage: 'apply', label: 'apply' },
  { stage: 'review', label: 'review' },
  { stage: 'archive', label: 'archive' },
]

export const MAX_REVIEW_ROUNDS = 3

const CHANGES_DIR = 'sdd/changes'
const ARCHIVE_DIR = `${CHANGES_DIR}/archive`

export function parseTitle(proposal: string, fallback: string): string {
  return proposal.match(/^#\s+(.+?)\s*$/m)?.[1] ?? fallback
}

export function parseProposalStatus(proposal: string): SddProposalStatus {
  const status = proposal.match(/^Статус:\s*(черновик|согласовано)\s*$/im)?.[1]?.toLowerCase()

  return status === 'черновик' || status === 'согласовано' ? status : 'не указан'
}

export function parseTasks(tasks: string): SddTasks {
  let done = 0
  let total = 0
  let next: string | null = null

  for (const [, mark, text] of tasks.matchAll(/^\s*- \[([ xX])\]\s*(.*)$/gm)) {
    total += 1
    if (mark === ' ') {
      next ??= text?.trim() ?? ''
    } else {
      done += 1
    }
  }

  return { done, total, next }
}

export function parseReview(review: string): SddReview {
  const round = Number(review.match(/^Раунд:\s*(\d+)/m)?.[1] ?? Number.NaN)
  const afterHeading = review.split(/^## Вердикт\s*$/m)[1] ?? ''
  const summary = afterHeading.split('\n').map(line => line.trim()).find(Boolean) ?? ''
  const normalized = summary.toLowerCase()
  const verdict = normalized.startsWith('не пройдено')
    ? 'не пройдено'
    : normalized.startsWith('пройдено')
      ? 'пройдено'
      : 'нет вердикта'

  return { round: Number.isNaN(round) ? null : round, verdict, summary }
}

type Progress = Pick<SddChange, 'stage' | 'nextStep' | 'nextSkill'>

export function deriveProgress(
  change: Pick<SddChange, 'proposal' | 'hasDesign' | 'tasks' | 'review'>,
): Progress {
  const { proposal, hasDesign, tasks, review } = change

  if (proposal === null) {
    return { stage: 'proposal', nextStep: 'создать proposal', nextSkill: 'sdd-propose' }
  }

  if (tasks === null) {
    if (proposal !== 'согласовано') {
      return { stage: 'proposal', nextStep: 'согласовать proposal', nextSkill: 'sdd-propose' }
    }
    if (hasDesign) {
      return { stage: 'tasks', nextStep: 'разбить на задачи', nextSkill: 'sdd-tasks' }
    }

    return {
      stage: 'design',
      nextStep: 'проработать design или сразу разбить на задачи',
      nextSkill: 'sdd-design',
    }
  }

  const isImplemented = tasks.total > 0 && tasks.done === tasks.total

  if (!isImplemented) {
    const nextStep =
      review?.verdict === 'не пройдено'
        ? `исправить замечания раунда ${review.round ?? '?'}`
        : 'продолжить реализацию'

    return { stage: 'apply', nextStep, nextSkill: 'sdd-apply' }
  }

  if (review === null) {
    return { stage: 'review', nextStep: 'запустить ревью', nextSkill: 'sdd-review' }
  }

  if (review.verdict === 'пройдено') {
    return { stage: 'archive', nextStep: 'архивировать изменение', nextSkill: 'sdd-archive' }
  }

  if (review.verdict === 'нет вердикта') {
    return { stage: 'review', nextStep: 'повторить ревью: вердикта нет', nextSkill: 'sdd-review' }
  }

  if ((review.round ?? 0) >= MAX_REVIEW_ROUNDS) {
    return {
      stage: 'review',
      nextStep: `лимит ${MAX_REVIEW_ROUNDS} раундов исчерпан: нужно ваше решение`,
      nextSkill: null,
    }
  }

  return {
    stage: 'review',
    nextStep: 'добавить задачи по замечаниям и исправить',
    nextSkill: 'sdd-apply',
  }
}

async function readIfExists($: EngineInterface, path: string): Promise<string | null> {
  return (await $.fs.exists(path)) ? $.fs.read(path) : null
}

async function scanChange($: EngineInterface, id: string): Promise<SddChange> {
  const dir = `${CHANGES_DIR}/${id}`
  const [proposalText, tasksText, reviewText, hasDesign, entries] = await Promise.all([
    readIfExists($, `${dir}/proposal.md`),
    readIfExists($, `${dir}/tasks.md`),
    readIfExists($, `${dir}/review.md`),
    $.fs.exists(`${dir}/design.md`),
    $.fs.list(dir),
  ])
  const facts = {
    proposal: proposalText === null ? null : parseProposalStatus(proposalText),
    hasDesign,
    tasks: tasksText === null ? null : parseTasks(tasksText),
    review: reviewText === null ? null : parseReview(reviewText),
  }

  return {
    id,
    title: proposalText === null ? id : parseTitle(proposalText, id),
    ...facts,
    ...deriveProgress(facts),
    updatedAt: Math.max(0, ...entries.map(entry => entry.mtimeMs)),
  }
}

async function listDirs($: EngineInterface, path: string): Promise<string[]> {
  if (!(await $.fs.exists(path))) {
    return []
  }

  return (await $.fs.list(path)).filter(entry => entry.kind === 'dir').map(entry => entry.name)
}

export async function scanBoard($: EngineInterface): Promise<SddBoard> {
  const hasSdd = await $.fs.exists('sdd')
  const ids = (await listDirs($, CHANGES_DIR)).filter(name => name !== 'archive')
  const changes = await Promise.all(ids.map(id => scanChange($, id)))
  const archived = (await listDirs($, ARCHIVE_DIR)).sort().reverse()

  return {
    hasSdd,
    changes: changes.sort((a, b) => b.updatedAt - a.updatedAt),
    archived,
  }
}
