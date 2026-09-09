import { describe, expect, it, vi } from "vitest";

import { createProject, getProjects } from "../apps/frontend/lib/projects.js";

describe("frontend project API helpers", () => {
  it("loads the accessible project list", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({ items: [{ id: "project-1", name: "Demo" }] }),
          { status: 200 },
        ),
      );
    await expect(getProjects()).resolves.toEqual([
      { id: "project-1", name: "Demo" },
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/projects",
      { credentials: "include" },
    );
    fetchMock.mockRestore();
  });

  it("creates a project through the authenticated API", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "project-1", name: "Demo" }), {
        status: 201,
      }),
    );
    await expect(
      createProject({ name: "Demo", description: "", domain: "General Task" }),
    ).resolves.toEqual({ id: "project-1", name: "Demo" });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/projects",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    fetchMock.mockRestore();
  });
});
