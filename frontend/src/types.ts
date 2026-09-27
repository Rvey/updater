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
  shipped_at: string;
  created_at: string;
  questions: Question[];
  impact_notes: ImpactNote[];
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
