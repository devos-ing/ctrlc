import type { ShowcaseNode } from '../generated/showcases'

type NodeListProps = {
  nodes: ShowcaseNode[]
  onSelect: (nodeId: string) => void
}

export function NodeList({ nodes, onSelect }: NodeListProps) {
  return (
    <ul className="node-list" aria-label="Saved scene elements">
      {nodes.map((node) => (
        <li key={node.id}>
          <button type="button" onClick={() => onSelect(node.id)}>
            <span>{node.name}</span>
            <span>{node.type}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
