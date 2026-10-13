export type GitHubRepositoryInput = { owner: string; repo: string };

export function parseGitHubRepository(value: string): GitHubRepositoryInput {
  const trimmed = value.trim();
  let parts: string[];
  if (/^https?:\/\//i.test(trimmed)) {
    let url: URL;
    try {
      url = new URL(trimmed);
    } catch {
      throw new Error("Enter a valid GitHub repository URL.");
    }
    if (
      url.protocol !== "https:" ||
      url.hostname.toLowerCase() !== "github.com" ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      throw new Error("Use the HTTPS URL of a repository on github.com.");
    }
    parts = url.pathname.replace(/\/$/, "").split("/").filter(Boolean);
  } else {
    parts = trimmed.replace(/\/$/, "").split("/");
  }
  if (parts.length < 2) {
    throw new Error(
      "This is a GitHub profile. Open a specific repository and copy its URL, such as https://github.com/uzair592/promptpilot.",
    );
  }
  if (parts.length !== 2) {
    throw new Error("Enter one repository as owner/repo or its GitHub URL.");
  }
  const [owner, repoValue] = parts;
  const repo = repoValue.replace(/\.git$/i, "");
  if (
    !/^[a-z\d](?:[a-z\d-]{0,38})$/i.test(owner) ||
    !/^[a-z\d_.-]{1,100}$/i.test(repo)
  ) {
    throw new Error("The GitHub owner or repository name is invalid.");
  }
  return { owner, repo };
}
