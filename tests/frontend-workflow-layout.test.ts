import { describe, expect, it } from "vitest";
import {
  layoutWorkflow,
  readyWorkflowTasks,
} from "../apps/frontend/lib/workflow-layout.js";
import type { AgentTask } from "../apps/frontend/lib/orchestration.js";

function task(id: string, dependencies: string[] = []): AgentTask {
  return {
    id,
    dependencies,
    project_id: "project",
    plan_id: "plan",
    milestone_id: "phase",
    title: id,
    description: "Task",
    role: "frontend",
    assignment_reason: "Selected",
    assigned_connection_id: "provider",
    assigned_provider: "gemini",
    assigned_model: "model",
    acceptance_criteria: [],
    status: "ready",
    scheduled_for: null,
    output_text: null,
    pull_request_url: null,
    last_error: null,
    attempt_count: 0,
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
  };
}
describe("visual workflow layout and readiness", () => {
  it("keeps independent implementation branches parallel and QA downstream", () => {
    const positions = layoutWorkflow([
      task("api"),
      task("frontend", ["api"]),
      task("backend", ["api"]),
      task("qa", ["frontend", "backend"]),
    ]);
    expect(positions.frontend.x).toBe(positions.backend.x);
    expect(positions.frontend.y).not.toBe(positions.backend.y);
    expect(positions.qa.x).toBeGreaterThan(positions.frontend.x);
  });
  it("rejects cycles and missing prerequisite nodes", () => {
    expect(() => layoutWorkflow([task("a", ["b"]), task("b", ["a"])])).toThrow(
      /cycle/,
    );
    expect(() => layoutWorkflow([task("a", ["missing"])])).toThrow(/missing/);
  });
  it("runs only assigned tasks with satisfied dependencies and reached start times", () => {
    const api = { ...task("api"), status: "review" };
    const frontend = task("frontend", ["api"]),
      qa = task("qa", ["frontend"]);
    const future = { ...task("future"), scheduled_for: "2999-01-01T00:00:00Z" };
    expect(
      readyWorkflowTasks([api, frontend, qa, future], ["provider"]).map(
        (item) => item.id,
      ),
    ).toEqual(["frontend"]);
    expect(readyWorkflowTasks([frontend], [])).toEqual([]);
  });
});
