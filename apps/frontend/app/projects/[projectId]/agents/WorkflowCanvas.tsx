"use client";

import { PointerEvent, useEffect, useRef, useState } from "react";
import type { AgentTask } from "../../../../lib/orchestration";
import {
  layoutWorkflow,
  NODE_HEIGHT,
  NODE_WIDTH,
  NodePosition,
} from "../../../../lib/workflow-layout";

export const roleNames: Record<AgentTask["role"], string> = {
  orchestrator: "Team lead",
  product_manager: "Product manager",
  researcher: "Research",
  frontend: "Frontend",
  backend: "Backend",
  api: "API design",
  tester: "QA review",
};
const roleMarks: Record<AgentTask["role"], string> = {
  orchestrator: "TL",
  product_manager: "PM",
  researcher: "R",
  frontend: "UI",
  backend: "BE",
  api: "API",
  tester: "QA",
};

export function WorkflowCanvas({
  planId,
  tasks,
  title,
  selectedId,
  onSelect,
  layoutVersion,
}: {
  planId: string;
  tasks: AgentTask[];
  title: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
  layoutVersion: number;
}) {
  const [positions, setPositions] = useState<Record<string, NodePosition>>({});
  const [zoom, setZoom] = useState(0.8);
  const [pan, setPan] = useState({ x: 24, y: 50 });
  const view = useRef<HTMLDivElement>(null);
  const arrangedVersion = useRef(0);
  const dragging = useRef<{
    id: string | null;
    x: number;
    y: number;
    start: NodePosition;
    moved: boolean;
  } | null>(null);
  const key = `promptpilot:workflow-layout:${planId}`;
  useEffect(() => {
    const defaults = layoutWorkflow(tasks);
    try {
      const saved = JSON.parse(localStorage.getItem(key) || "{}") as Record<
        string,
        NodePosition
      >;
      for (const id of Object.keys(defaults))
        if (Number.isFinite(saved[id]?.x) && Number.isFinite(saved[id]?.y))
          defaults[id] = saved[id];
    } catch {
      /* A damaged local layout can be rebuilt from dependencies. */
    }
    setPositions(defaults);
  }, [key, tasks]);
  useEffect(() => {
    if (layoutVersion === arrangedVersion.current) return;
    arrangedVersion.current = layoutVersion;
    const defaults = layoutWorkflow(tasks);
    setPositions(defaults);
    localStorage.setItem(key, JSON.stringify(defaults));
    setPan({ x: 24, y: 50 });
  }, [layoutVersion, key, tasks]);
  function start(event: PointerEvent, id: string | null) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragging.current = {
      id,
      x: event.clientX,
      y: event.clientY,
      start: id ? positions[id] : pan,
      moved: false,
    };
  }
  function move(event: PointerEvent) {
    const drag = dragging.current;
    if (!drag) return;
    const dx = event.clientX - drag.x,
      dy = event.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    if (drag.id)
      setPositions((current) => ({
        ...current,
        [drag.id!]: {
          x: Math.max(0, drag.start.x + dx / zoom),
          y: Math.max(0, drag.start.y + dy / zoom),
        },
      }));
    else setPan({ x: drag.start.x + dx, y: drag.start.y + dy });
  }
  function finish() {
    const drag = dragging.current;
    if (!drag) return;
    if (drag.id) {
      localStorage.setItem(key, JSON.stringify(positions));
      if (!drag.moved) onSelect(drag.id);
    }
    dragging.current = null;
  }
  function fit() {
    const width = Math.max(
      600,
      ...Object.values(positions).map((item) => item.x + NODE_WIDTH + 50),
    );
    const height = Math.max(
      420,
      ...Object.values(positions).map((item) => item.y + NODE_HEIGHT + 50),
    );
    setZoom(
      Math.min(
        1,
        Math.max(
          0.25,
          Math.min(
            (view.current?.clientWidth ?? 1000) / width,
            (view.current?.clientHeight ?? 600) / height,
          ),
        ),
      ),
    );
    setPan({ x: 15, y: 20 });
  }
  const roots = tasks.filter((task) => !task.dependencies.length);
  const rootY = roots.length ? (positions[roots[0].id]?.y ?? 80) : 80;
  return (
    <div
      className="workflow-canvas"
      ref={view}
      aria-label="Workflow canvas"
      onPointerDown={(event) => start(event, null)}
      onPointerMove={move}
      onPointerUp={finish}
      onPointerCancel={finish}
    >
      <div
        className="workflow-world"
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
        }}
      >
        <svg
          className="workflow-edges"
          width="12000"
          height="12000"
          aria-hidden="true"
        >
          <defs>
            <marker
              id="workflow-arrow"
              markerWidth="7"
              markerHeight="7"
              refX="6"
              refY="3.5"
              orient="auto"
            >
              <path d="M0,0 L7,3.5 L0,7" fill="#a4a9bc" />
            </marker>
          </defs>
          {tasks.flatMap((task) =>
            (task.dependencies.length ? task.dependencies : ["input"]).map(
              (parent) => {
                const from =
                    parent === "input"
                      ? { x: 34, y: rootY }
                      : positions[parent],
                  to = positions[task.id];
                if (!from || !to) return null;
                const x1 = from.x + (parent === "input" ? 190 : NODE_WIDTH),
                  y1 = from.y + NODE_HEIGHT / 2,
                  x2 = to.x,
                  y2 = to.y + NODE_HEIGHT / 2;
                return (
                  <path
                    key={`${parent}-${task.id}`}
                    d={`M${x1},${y1} C${x1 + 60},${y1} ${x2 - 60},${y2} ${x2},${y2}`}
                    className={selectedId === task.id ? "edge-selected" : ""}
                    markerEnd="url(#workflow-arrow)"
                  />
                );
              },
            ),
          )}
        </svg>
        <div className="workflow-input" style={{ left: 34, top: rootY }}>
          <span className="node-icon input-icon">↗</span>
          <small>PROJECT INPUT</small>
          <strong>{title}</strong>
          <span>Goal and saved context</span>
        </div>
        {tasks.map((task) => (
          <button
            key={task.id}
            className={`workflow-node node-${task.role} status-${task.status} ${selectedId === task.id ? "node-selected" : ""}`}
            aria-label={`Configure ${task.title}`}
            aria-pressed={selectedId === task.id}
            style={{
              left: positions[task.id]?.x ?? 300,
              top: positions[task.id]?.y ?? 80,
              width: NODE_WIDTH,
              height: NODE_HEIGHT,
            }}
            onPointerDown={(event) => start(event, task.id)}
            onPointerMove={move}
            onPointerUp={finish}
            onClick={(event) => {
              if (event.detail === 0) onSelect(task.id);
            }}
          >
            <span className="node-port node-input-port" />
            <span className="node-port node-output-port" />
            <div className="node-top">
              <span className={`node-icon role-icon-${task.role}`}>
                {roleMarks[task.role]}
              </span>
              <span className="node-status">
                <i />
                {task.status === "review"
                  ? "Review output"
                  : task.status === "backlog"
                    ? "Not started"
                    : task.status}
              </span>
            </div>
            <strong>{task.title}</strong>
            <small>{roleNames[task.role]}</small>
            <div className="node-model">
              {task.assigned_model || "＋ Assign a model"}
            </div>
          </button>
        ))}
      </div>
      <div className="canvas-hint">
        Drag to pan · Drag nodes to arrange · Select a node to configure
      </div>
      <div
        className="canvas-controls"
        onPointerDown={(event) => event.stopPropagation()}
      >
        <button
          aria-label="Zoom out"
          onClick={() => setZoom((value) => Math.max(0.25, value - 0.1))}
        >
          −
        </button>
        <span>{Math.round(zoom * 100)}%</span>
        <button
          aria-label="Zoom in"
          onClick={() => setZoom((value) => Math.min(1.5, value + 0.1))}
        >
          ＋
        </button>
        <button onClick={fit}>Fit workflow</button>
      </div>
    </div>
  );
}
