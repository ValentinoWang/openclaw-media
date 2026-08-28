import assert from 'node:assert/strict'

import { filterWorkboardAttentionTasks } from '../../src/media/studio/workboardPresentation'

const tasks = [
  { taskId: 'failed-terminal', status: 'failed', terminal: true },
  { taskId: 'manual-terminal', status: 'pending_manual', terminal: true },
  { taskId: 'confirmation', status: 'awaiting_confirmation', terminal: false },
  { taskId: 'attention', status: 'needs_attention', terminal: false },
  { taskId: 'succeeded-terminal', status: 'succeeded', terminal: true },
  { taskId: 'readback-complete', status: 'multi_system_readback_complete', terminal: true },
  { taskId: 'running', status: 'generating', terminal: false },
] as const

assert.deepEqual(
  filterWorkboardAttentionTasks(tasks).map((task) => task.taskId),
  ['failed-terminal', 'manual-terminal', 'confirmation', 'attention'],
  'failed and manual-action tasks must remain visible even after they are terminal',
)

console.log('workboard task attention checks passed')
