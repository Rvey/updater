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
  external_id: string | null;
  title: string;
  summary: string;
  repo_url: string;
  branch: string | null;
  commit_sha: string | null;
  pr_url: string | null;
  author_agent: string | null;
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
