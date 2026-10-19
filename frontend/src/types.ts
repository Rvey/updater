export type CodeExcerpt = {
  path: string;
  content: string;
  start_line: number | null;
  end_line: number | null;
};

export type ContextRequest = {
  id: string;
  update_id: string;
  question: string;
  status: string;
  excerpts: CodeExcerpt[];
  source_repo_url: string | null;
  source_branch: string | null;
  source_commit: string | null;
  claimed_at: string | null;
  claimed_by: string | null;
  created_at: string;
  fulfilled_at: string | null;
};

export type Question = {
  id: string;
  question: string;
  answer: string;
  source: "ai" | "saved-context";
  created_at: string;
};

export type ImpactNote = {
  id: string;
  note: string;
  created_at: string;
};

export type NoteColor =
  | "default"
  | "red"
  | "orange"
  | "yellow"
  | "green"
  | "blue"
  | "purple"
  | "pink";

export type NoteCategory =
  | "todo"
  | "bug"
  | "idea"
  | "investigation"
  | "implementation"
  | "command"
  | "decision"
  | "follow-up"
  | "general";

export type NoteStatus = "open" | "in-progress" | "done" | "archived";

export type NotePriority = "none" | "low" | "medium" | "high";

export type Note = {
  id: string;
  project_id?: string | null;
  title: string;
  content: string;
  color: NoteColor;
  category: NoteCategory;
  status: NoteStatus;
  priority: NotePriority;
  tags: string[];
  repository: string | null;
  branch: string | null;
  file_path: string | null;
  commit_hash: string | null;
  related_url: string | null;
  due_date: string | null;
  pinned: boolean;
  archived: boolean;
  created_at: string;
  updated_at: string;
};

export type Update = {
  id: string;
  project_id?: string | null;
  external_id: string | null;
  title: string;
  summary: string;
  repo_url: string;
  branch: string | null;
  commit_sha: string | null;
  pr_url: string | null;
  author_agent: string | null;
  user_id?: string | null;
  why: string;
  how_it_works: string;
  impact: string;
  tradeoffs: string;
  learning_notes: string;
  files_changed: string[];
  tags: string[];
  code_context: CodeExcerpt[];
  shipped_at: string;
  created_at: string;
  questions: Question[];
  impact_notes: ImpactNote[];
  context_requests: ContextRequest[];
};

export type NewUpdate = Pick<
  Update,
  "title" | "summary" | "repo_url" | "why" | "how_it_works" | "impact"
> & {
  tradeoffs?: string;
  learning_notes?: string;
  files_changed?: string[];
  tags?: string[];
};

export type TechDebtUrgency = "low" | "medium" | "high" | "critical";

export type TechDebtStatus = "open" | "in-progress" | "resolved" | "wont-fix";

export type TechDebt = {
  id: string;
  project_id?: string | null;
  title: string;
  scope: string;
  description: string;
  impact: string;
  mitigation: string;
  current_state: string;
  urgency: TechDebtUrgency;
  status: TechDebtStatus;
  repo_url: string;
  file_path: string | null;
  files: string[];
  tags: string[];
  branch: string | null;
  commit_sha: string | null;
  author_agent: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
};

export type NewTechDebt = Pick<
  TechDebt,
  "title" | "scope" | "description" | "impact" | "mitigation" | "current_state" | "repo_url"
> & {
  urgency?: TechDebtUrgency;
  file_path?: string;
  files?: string[];
  tags?: string[];
  branch?: string;
  commit_sha?: string;
};

export type TaskStatus = "backlog" | "in-progress" | "review" | "done";

export type TaskPriority = "low" | "medium" | "high";

export type Task = {
  id: string;
  project_id?: string | null;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  position: number;
  repo_url: string | null;
  branch: string | null;
  tags: string[];
  assignee: string | null;
  due_date: string | null;
  author_agent: string | null;
  external_id?: string | null;
  external_url?: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type DelegationStatus =
  | "queued"
  | "running"
  | "pr_opened"
  | "failed"
  | "cancelled";

export type Delegation = {
  id: string;
  task_id: string;
  project_id: string | null;
  repo: string;
  issue_number: number | null;
  status: DelegationStatus;
  branch: string | null;
  pr_url: string | null;
  pr_number: number | null;
  error: string | null;
  summary: string | null;
  claimed_by: string | null;
  claimed_at: string | null;
  task_title: string;
  task_description: string | null;
  issue_url: string | null;
  suggested_branch: string | null;
  instruction: string | null;
  base_branch: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
};

export type GitHubSyncResult = {
  repo: string;
  created: number;
  updated: number;
  total: number;
  truncated?: boolean;
};

export type GitHubRepo = {
  full_name: string;
  private: boolean;
  default_branch: string;
  linked: boolean;
  project_id: string | null;
};

export type GitHubItem = {
  number: number;
  title: string;
  body: string;
  state: string;
  merged: boolean;
  draft: boolean;
  url: string;
  author: string | null;
  assignees: string[];
  labels: string[];
  comments: number;
  is_pr: boolean;
  updated_at: string;
  branch: string | null;
  task_id: string | null;
};

export type GitHubItemsPage = {
  items: GitHubItem[];
  next_page: number | null;
};

export type GitHubLink = {
  id: string;
  repo: string;
  created_at: string;
  last_event_at: string | null;
};

export type NewTask = Pick<Task, "title"> & {
  description?: string;
  status?: TaskStatus;
  priority?: TaskPriority;
  repo_url?: string | null;
  branch?: string | null;
  tags?: string[];
  assignee?: string | null;
  due_date?: string | null;
};

export type TaskUpdate = Partial<
  Pick<
    Task,
    | "title"
    | "description"
    | "status"
    | "priority"
    | "repo_url"
    | "branch"
    | "tags"
    | "assignee"
    | "due_date"
  >
>;

export type WorkspaceRole = "owner" | "member";

export type WorkspaceProject = {
  id: string;
  name: string;
  slug: string;
  repo_url: string | null;
  is_default: boolean;
};

export type Workspace = {
  id: string;
  name: string;
  slug: string;
  role: WorkspaceRole;
  projects: WorkspaceProject[];
};

export type Member = {
  user_id: string;
  email: string;
  role: WorkspaceRole;
  created_at: string;
};

export type Invite = {
  id: string;
  email: string;
  role: WorkspaceRole;
  expires_at: string;
  created_at?: string;
  token?: string;
};

export type AffinebotStatus = "pending" | "active" | "error";

export type AffinebotLink = {
  workspace_id: string;
  base_url: string;
  client_id: string;
  status: AffinebotStatus;
  github_owner: string | null;
  installation_id: number | null;
  last_checked_at: string | null;
  last_error: string | null;
};
