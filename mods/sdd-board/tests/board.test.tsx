import { expect, test } from 'claude-code/testing'

import { deriveProgress, parseProposalStatus, parseReview, parseTasks } from '../hooks/sdd'

const PROPOSAL = '# Экспорт пользователей\n\nСтатус: согласовано\n\n## Зачем\n...\n'
const TASKS = '## 1. API\n- [x] 1.1 Эндпоинт\n- [ ] 1.2 Тесты эндпоинта\n## 2. UI\n- [ ] 2.1 Кнопка\n'
const REVIEW_FAILED =
  '# Ревью add-export\n\nРаунд: 2\n\n## Вердикт\nне пройдено — 1 блокирующих замечаний по требованиям\n'
const REVIEW_PASSED_WITH_DECISION =
  '# Ревью\n\nРаунд: 1\n\n## Вердикт\n\nпройдено\nАрхивация вопреки вердикту: нет\n'

const FILES: Record<string, string> = {
  'sdd/changes/add-export/proposal.md': PROPOSAL,
  'sdd/changes/add-export/tasks.md': TASKS,
}
const DIRS: Record<string, { name: string; kind: 'file' | 'dir' }[]> = {
  sdd: [{ name: 'changes', kind: 'dir' }],
  'sdd/changes': [
    { name: 'add-export', kind: 'dir' },
    { name: 'archive', kind: 'dir' },
  ],
  'sdd/changes/add-export': [
    { name: 'proposal.md', kind: 'file' },
    { name: 'tasks.md', kind: 'file' },
  ],
  'sdd/changes/archive': [
    { name: '2026-10-01-add-login', kind: 'dir' },
    { name: '2026-10-15-fix-search', kind: 'dir' },
  ],
}

// The engine resolves the mod's relative paths against the working directory before the fs hooks see them.
const sddPath = (path: string) => path.match(/(?:^|\/)(sdd(?:\/.*)?)$/)?.[1] ?? path

const PANE = {
  plugin: 'sdd-board',
  component: 'Pane',
  requestId: 'sdd-board',
  props: {
    title: 'SDD',
    isFocused: false,
    bodyColumns: 50,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

test('proposal status, tasks and review verdict are parsed from the files', () => {
  expect(parseProposalStatus(PROPOSAL)).toBe('согласовано')
  expect(parseProposalStatus('# X\n\nСтатус: черновик\n')).toBe('черновик')
  expect(parseProposalStatus('# X\n')).toBe('не указан')

  expect(parseTasks(TASKS)).toEqual({ done: 1, total: 3, next: '1.2 Тесты эндпоинта' })

  expect(parseReview(REVIEW_FAILED)).toMatchObject({ round: 2, verdict: 'не пройдено' })
  expect(parseReview(REVIEW_PASSED_WITH_DECISION)).toEqual({
    round: 1,
    verdict: 'пройдено',
    summary: 'пройдено',
  })
  expect(parseReview('# Ревью\n')).toMatchObject({ round: null, verdict: 'нет вердикта' })
  expect(parseReview('## Вердикт\nПройдено\n').verdict).toBe('пройдено')
  expect(parseReview('## Вердикт\nНе пройдено — 1 блокирующих\n').verdict).toBe('не пройдено')
  expect(parseProposalStatus('# X\n\nСтатус: Согласовано\n')).toBe('согласовано')
})

test('the stage follows the SDD order', () => {
  const approved = { proposal: 'согласовано', hasDesign: false, tasks: null, review: null } as const
  const allDone = { done: 3, total: 3, next: null }
  const failed = { round: 1, verdict: 'не пройдено', summary: '' } as const

  expect(deriveProgress({ ...approved, proposal: 'черновик' }).stage).toBe('proposal')
  expect(deriveProgress(approved)).toMatchObject({ stage: 'design', nextSkill: 'sdd-design' })
  expect(deriveProgress({ ...approved, hasDesign: true }).nextSkill).toBe('sdd-tasks')
  expect(deriveProgress({ ...approved, tasks: { done: 1, total: 3, next: 'x' } }).stage).toBe('apply')
  expect(deriveProgress({ ...approved, tasks: allDone })).toMatchObject({
    stage: 'review',
    nextSkill: 'sdd-review',
  })
  expect(
    deriveProgress({ ...approved, tasks: { done: 3, total: 4, next: 'fix' }, review: failed }),
  ).toMatchObject({ stage: 'apply', nextStep: 'исправить замечания раунда 1' })
  expect(
    deriveProgress({ ...approved, tasks: allDone, review: { ...failed, round: 3 } }).nextSkill,
  ).toBe(null)
  expect(
    deriveProgress({
      ...approved,
      tasks: allDone,
      review: { round: 1, verdict: 'пройдено', summary: 'пройдено' },
    }),
  ).toMatchObject({ stage: 'archive', nextSkill: 'sdd-archive' })
})

test('the pane shows the active change and the archive, on every surface', async ($, on) => {
  on('command.register', () => ({ value: { command: 'sdd' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('clock.every', () => ({ value: undefined }))
  on('fs.exists', (_, e) => ({ value: sddPath(e.path) in FILES || sddPath(e.path) in DIRS }))
  on('fs.read', (_, e) => ({ value: FILES[sddPath(e.path)] ?? '' }))
  on('fs.list', (_, e) => ({
    value: (DIRS[sddPath(e.path)] ?? []).map(entry => ({
      ...entry,
      size: 0,
      mtimeMs: 0,
      isLink: false,
    })),
  }))

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })

    expect(await ui.find({ type: 'Text', text: 'Экспорт пользователей' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /1\/3/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Следующая: 1\.2 Тесты эндпоинта/ })).toBeDefined()
    expect((await ui.find({ key: 'next:add-export' }))?.text).toBe('/sdd-apply')
    expect(await ui.find({ type: 'Text', text: /^Proposal:/ })).toBeUndefined()

    const skippedDesign = (await ui.findAll({ type: 'Text' })).find(one => one.props.strikethrough)
    expect(skippedDesign?.text).toBe('design')

    const bar = await ui.find({ key: 'bar:add-export' })
    expect(bar?.props).toMatchObject({ backgroundColor: 'promptBorder', height: 1 })
    expect(bar?.children).toMatchObject([{ props: { width: '33%', backgroundColor: 'success' } }])
    expect(await ui.find({ type: 'Text', text: 'В архиве: 2' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /2026-10-15-fix-search/ })).toBeDefined()
    await ui.unmount()
  }
})
