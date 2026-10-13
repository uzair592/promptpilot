import { describe, expect, it } from "vitest";

import { parseGitHubRepository } from "../apps/frontend/lib/github-repository.js";

describe("GitHub repository input", () => {
  it("accepts a repository URL, .git URL, and owner/repo", () => {
    expect(
      parseGitHubRepository("https://github.com/uzair592/promptpilot"),
    ).toEqual({
      owner: "uzair592",
      repo: "promptpilot",
    });
    expect(
      parseGitHubRepository("https://github.com/uzair592/promptpilot.git/"),
    ).toEqual({
      owner: "uzair592",
      repo: "promptpilot",
    });
    expect(parseGitHubRepository("uzair592/promptpilot")).toEqual({
      owner: "uzair592",
      repo: "promptpilot",
    });
  });

  it("explains why a profile URL cannot identify a repository", () => {
    expect(() => parseGitHubRepository("https://github.com/uzair592")).toThrow(
      /profile.*specific repository/i,
    );
  });

  it("rejects another host, credentials, and extra path segments", () => {
    expect(() =>
      parseGitHubRepository("https://example.com/owner/repo"),
    ).toThrow();
    expect(() =>
      parseGitHubRepository("https://user:secret@github.com/owner/repo"),
    ).toThrow();
    expect(() =>
      parseGitHubRepository("https://github.com/owner/repo/issues"),
    ).toThrow();
  });
});
