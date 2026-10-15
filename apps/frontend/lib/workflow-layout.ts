import type { AgentTask } from "./orchestration.js";

export type NodePosition = { x: number; y: number };
export const NODE_WIDTH = 232;
export const NODE_HEIGHT = 146;

export function layoutWorkflow(
  tasks: AgentTask[],
): Record<string, NodePosition> {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const depths = new Map<string, number>();
  const visiting = new Set<string>();
  function depth(id: string): number {
    if (depths.has(id)) return depths.get(id)!;
    if (visiting.has(id)) throw new Error("Workflow has a dependency cycle");
    visiting.add(id);
    const parents = byId.get(id)?.dependencies ?? [];
    const value = parents.length
      ? Math.max(
          ...parents.map((parent) => {
            if (!byId.has(parent))
              throw new Error("Workflow references a missing node");
            return depth(parent) + 1;
          }),
        )
      : 0;
    visiting.delete(id);
    depths.set(id, value);
    return value;
  }
  const columns = new Map<number, AgentTask[]>();
  for (const task of tasks) {
    const column = depth(task.id);
    columns.set(column, [...(columns.get(column) ?? []), task]);
  }
  const maximumRows = Math.max(
    1,
    ...[...columns.values()].map((column) => column.length),
  );
  return Object.fromEntries(
    tasks.map((task) => {
      const column = depths.get(task.id)!;
      const rows = columns.get(column)!;
      return [
        task.id,
        {
          x: 300 + column * 310,
          y: 80 + (maximumRows - rows.length) * 95 + rows.indexOf(task) * 190,
        },
      ];
    }),
  );
}

export function readyWorkflowTasks(
  tasks: AgentTask[],
  connections: string[],
): AgentTask[] {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  return tasks.filter(
    (task) =>
      task.assigned_connection_id &&
      connections.includes(task.assigned_connection_id) &&
      ["backlog", "ready", "scheduled", "failed"].includes(task.status) &&
      (!task.scheduled_for || Date.parse(task.scheduled_for) <= Date.now()) &&
      task.dependencies.every((id) =>
        ["review", "completed"].includes(byId.get(id)?.status ?? ""),
      ),
  );
}
