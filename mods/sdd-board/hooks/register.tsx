import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { SddBoard, SddChange, SddTasks } from '../types'
import { STAGES, scanBoard } from './sdd'

const PANE = 'sdd-board'
const TITLE = 'SDD'
const RESCAN_MS = 10_000
const ARCHIVE_SHOWN = 5
const FILE_CHANGING_TOOLS = new Set(['Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Bash'])

const board = atom({ plugin: 'sdd-board', key: 'board' } as const, null)

async function refresh($: EngineInterface): Promise<SddBoard> {
  const scanned = await scanBoard($)
  const current = await read($, board)
  if (JSON.stringify(current) !== JSON.stringify(scanned)) {
    await update($, board, () => scanned)
  }

  return scanned
}

async function refreshQuietly($: EngineInterface): Promise<void> {
  try {
    await refresh($)
  } catch (error) {
    $.ui.log(`sdd-board: не удалось прочитать sdd/: ${String(error)}`)
  }
}

function percentDone({ done, total }: SddTasks): number {
  return total === 0 ? 0 : Math.round((done / total) * 100)
}

function describeChange(change: SddChange): string {
  const tasks = change.tasks ? `, задачи ${change.tasks.done}/${change.tasks.total}` : ''
  const review = change.review ? `, ревью: ${change.review.verdict}` : ''

  return `- ${change.id}: этап ${change.stage}${tasks}${review}; дальше: ${change.nextStep}`
}

function describeBoard(scanned: SddBoard): string {
  if (!scanned.hasSdd) {
    return 'В рабочем каталоге нет sdd/.'
  }
  if (scanned.changes.length === 0) {
    return `Активных SDD-изменений нет. В архиве: ${scanned.archived.length}.`
  }

  return ['Активные SDD-изменения:', ...scanned.changes.map(describeChange)].join('\n')
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'sdd',
      description: 'Открыть панель SDD с этапами активных изменений',
    })
    const scanned = await refresh($)
    if (scanned.hasSdd) {
      void $.ui.open({ id: PANE, title: TITLE })
    }
    $.clock.every(RESCAN_MS, () => void refreshQuietly($))

    return next(e)
  })

  on('command.run', { command: 'sdd' }, async $ => {
    const scanned = await refresh($)
    await $.ui.open({ id: PANE, title: TITLE })

    return { text: describeBoard(scanned) }
  })

  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    if (FILE_CHANGING_TOOLS.has(String(e.tool))) {
      await refreshQuietly($)
    }

    return result
  })

  on('turn.complete', async ($, e, next) => {
    await refreshQuietly($)

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const scanned = await read($, board)
    const barWidth = Math.max(6, Math.min(24, e.props.bodyColumns - 14))

    const refreshButton = (
      <Button key="refresh" label="Обновить" onPress={() => refreshQuietly($)} />
    )

    if (scanned === null || !scanned.hasSdd) {
      return (
        <Box flexDirection="column" gap={1}>
          <Text dimColor>В рабочем каталоге нет sdd/.</Text>
          {refreshButton}
        </Box>
      )
    }

    const stageMarks = (change: SddChange) => {
      const current = STAGES.findIndex(one => one.stage === change.stage)

      return (
        <Text>
          {STAGES.flatMap(({ stage, label }, index) => {
            const separator = index === 0 ? [] : [<Text dimColor> › </Text>]
            if (stage === 'design' && !change.hasDesign && index < current) {
              return [...separator, <Text dimColor strikethrough>{label}</Text>]
            }
            if (index < current) {
              return [...separator, <Text color="success">✓ {label}</Text>]
            }
            if (index === current) {
              return [...separator, <Text color="claude" bold>▶ {label}</Text>]
            }

            return [...separator, <Text dimColor>{label}</Text>]
          })}
        </Text>
      )
    }

    const changeCard = (change: SddChange) => (
      <Box
        key={change.id}
        flexDirection="column"
        borderStyle="round"
        borderColor={change.stage === 'archive' ? 'success' : 'promptBorder'}
        paddingX={1}
      >
        <Text bold wrap="truncate-end">{change.title}</Text>
        <Text dimColor wrap="truncate-end">{change.id}</Text>
        {stageMarks(change)}
        {change.stage === 'proposal' && change.proposal !== null && (
          <Text color={change.proposal === 'черновик' ? 'warning' : 'subtle'}>
            Proposal: {change.proposal}
          </Text>
        )}
        {change.tasks !== null && (
          <Box flexDirection="row" alignItems="center" gap={1}>
            <Box key={`bar:${change.id}`} width={barWidth} height={1} backgroundColor="promptBorder">
              <Box
                width={`${percentDone(change.tasks)}%`}
                height={1}
                backgroundColor="success"
              />
            </Box>
            <Text tabular>{change.tasks.done}/{change.tasks.total}</Text>
          </Box>
        )}
        {change.tasks?.next != null && (
          <Text dimColor wrap="truncate-end">Следующая: {change.tasks.next}</Text>
        )}
        {change.review !== null && (
          <Text
            color={change.review.verdict === 'пройдено' ? 'success' : 'error'}
            wrap="truncate-end"
          >
            Ревью, раунд {change.review.round ?? '?'}: {change.review.summary || change.review.verdict}
          </Text>
        )}
        <Box flexDirection="row" gap={1} alignItems="center">
          <Text>Дальше: {change.nextStep}</Text>
          {change.nextSkill !== null && (
            <Button
              key={`next:${change.id}`}
              label={`/${change.nextSkill}`}
              variant="primary"
              onPress={() =>
                $.prompt.fill({ text: `/${change.nextSkill} ${change.id}`, mode: 'replace' })
              }
            />
          )}
        </Box>
      </Box>
    )

    return (
      <Box flexDirection="column" gap={1}>
        <Box flexDirection="row" justifyContent="space-between" alignItems="center">
          <Text bold>
            {scanned.changes.length === 0
              ? 'Активных изменений нет'
              : `Активных изменений: ${scanned.changes.length}`}
          </Text>
          {refreshButton}
        </Box>
        {scanned.changes.map(changeCard)}
        {scanned.archived.length > 0 && (
          <Box flexDirection="column">
            <Text dimColor>В архиве: {scanned.archived.length}</Text>
            {scanned.archived.slice(0, ARCHIVE_SHOWN).map(name => (
              <Text dimColor wrap="truncate-end">  {name}</Text>
            ))}
          </Box>
        )}
      </Box>
    )
  })
}
