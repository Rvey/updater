/** Repository identity is independent of the agent or remote URL spelling. */
export function repositoryKey(value: string | null | undefined): string {
  let url = (value || "").trim().replace(/\/+$/, "");
  url = url.replace(/^git@([^:]+):/, "https://$1/");
  url = url.replace(/^ssh:\/\/(?:git@)?/, "https://");
  url = url.replace(/^http:\/\//, "https://");
  return url.replace(/\.git$/i, "").replace(/\/+$/, "").toLowerCase();
}

export function uniqueRepositories(values: string[]): string[] {
  const repositories = new Map<string, string>();
  for (const value of values) {
    const key = repositoryKey(value);
    if (key && !repositories.has(key)) repositories.set(key, value);
  }
  return [...repositories.values()];
}
