import { useMemo } from 'react'
import { ReactFlow, Background, Handle, Position, MarkerType } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

const SOURCE_COLORS = { whatsapp: 'var(--wa)', gmail: 'var(--gm)' }

function SiftNode({ data }) {
  return (
    <div
      className={`flow-node${data.onClick ? ' flow-node-click' : ''}`}
      style={data.accent ? { borderColor: data.accent } : undefined}
      onClick={data.onClick}
      role={data.onClick ? 'button' : undefined}
    >
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <div className="flow-node-label" style={data.accent ? { color: data.accent } : undefined}>
        {data.label}
      </div>
      {data.title && <div className="flow-node-title">{data.title}</div>}
      {(data.lines || []).map((line, i) => (
        <div key={i} className="flow-node-line">
          {line}
        </div>
      ))}
      <Handle type="source" position={Position.Right} className="flow-handle" />
    </div>
  )
}

const nodeTypes = { sift: SiftNode }

const truncate = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s)

function stepSpec(step, table) {
  if (step.type === 'fetch') {
    const window = step.since_days
      ? `since ${step.since_days}d`
      : [step.from_date, step.to_date].filter(Boolean).join(' → ') || 'all time'
    const scope = step.chat_jids ? `${step.chat_jids.length} chats` : 'scoped chats'
    return {
      label: `● ${(step.source || '?').toUpperCase()}`,
      accent: SOURCE_COLORS[step.source],
      title: 'fetch',
      lines: [window, scope],
    }
  }
  if (step.type === 'filter') {
    return { label: 'FILTER', title: 'llm', lines: [truncate(step.instruction || '', 76)] }
  }
  if (step.type === 'extract') {
    const cols = table && table.columns ? table.columns.map((c) => c.name) : null
    return {
      label: 'EXTRACT',
      title: 'typed',
      lines: [cols ? truncate(cols.join(' · '), 76) : 'columns = table schema'],
    }
  }
  if (step.type === 'upsert') {
    const keys =
      step.dedupe_on && step.dedupe_on.length
        ? step.dedupe_on
        : (table && table.dedupe_keys) || []
    return {
      label: 'UPSERT',
      title: keys.length ? `dedupe ${keys.join(', ')}` : 'insert only',
    }
  }
  return { label: (step.type || '?').toUpperCase() }
}

function buildGraph(dsl, table, onOpenTable, onEditTrigger) {
  const trigger = dsl && dsl.trigger
  const specs = [
    {
      label: 'TRIGGER',
      title:
        trigger && typeof trigger === 'object'
          ? `every ${trigger.minutes}m`
          : trigger || 'manual',
      lines: onEditTrigger ? ['✎ edit'] : [],
      onClick: onEditTrigger,
    },
    ...((dsl && dsl.steps) || []).map((step) => stepSpec(step, table)),
  ]
  if (dsl && dsl.table) {
    specs.push({
      label: 'TABLE',
      title: dsl.table,
      lines: table && table.record_count != null ? [`${table.record_count} rows`] : [],
      accent: 'var(--cobalt)',
      onClick: onOpenTable ? () => onOpenTable(dsl.table) : undefined,
    })
  }

  const nodes = specs.map((data, i) => ({
    id: String(i),
    type: 'sift',
    position: { x: i * 200, y: 0 },
    data,
  }))
  const edges = nodes.slice(1).map((node, i) => ({
    id: `e${i}`,
    source: String(i),
    target: node.id,
    animated: true,
    style: { stroke: 'var(--cobalt)' },
    markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--cobalt)' },
  }))
  return { nodes, edges }
}

export default function WorkflowFlow({
  dsl,
  table,
  onOpenTable,
  onEditTrigger,
  interactive = false,
  large = false,
}) {
  const { nodes, edges } = useMemo(
    () => buildGraph(dsl, table, onOpenTable, onEditTrigger),
    [dsl, table, onOpenTable, onEditTrigger],
  )
  return (
    <div className={large ? 'wf-flow wf-flow-lg' : 'wf-flow'}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: large ? 0.2 : 0.12 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={interactive}
        zoomOnScroll={interactive}
        zoomOnPinch={interactive}
        zoomOnDoubleClick={false}
        preventScrolling={interactive}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={18} size={1} color="#27272f" />
      </ReactFlow>
    </div>
  )
}
