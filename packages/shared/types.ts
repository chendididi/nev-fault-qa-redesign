export type Role = "admin" | "technician";

export type DiagnosticAnswer = {
  possible_causes: string[];
  inspection_steps: string[];
  safety_notes: string[];
  repair_suggestions: string[];
  citations: Citation[];
  confidence_note: string;
};

export type Citation = {
  id: string;
  title: string;
  filename: string;
  content: string;
  score: number;
};

export type ModelConfig = {
  provider: "openai_compatible";
  base_url: string;
  api_key: string;
  chat_model: string;
  embedding_model: string;
  vision_model?: string;
  rerank_model?: string;
  embedding_dim: number;
};
