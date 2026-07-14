/**
 * Shared TypeScript interfaces for the entire app.
 * All API response shapes and UI constants live here.
 */

// ── Book ──

export interface Book {
  id: number;
  title: string;
  author: string;
  status: string;
  created: string;
  has_clean: boolean;
  has_ner: boolean;
  has_chunks: boolean;
  has_chapters: boolean;
}

// ── NER ──

export interface NerEntity {
  word: string;
  label: string;
  score: number;
  start: number;
  end: number;
}

export interface NerResult {
  book_name: string;
  total_entities: number;
  entities: NerEntity[];
}

// ── Chapters ──

export interface ChapterSummary {
  id: number;
  level: number;
  content: string;
}

export interface Chapter {
  id: number;
  chapter_id_num: number;
  title: string;
  char_start: number;
  char_end: number;
  summaries: ChapterSummary[];
}

// ── Semantic Chunks ──

export interface SemanticChunk {
  book_name: string;
  chunk_id: number;
  total_chunks: number;
  text: string;
  char_start: number;
  char_end: number;
  topic_hint: string;
  entities: { word: string; label: string; score: number }[];
}

// ── NER Retention ──

export interface NerRetention {
  total_entities: number;
  found: number;
  retention_percent: number;
  lost?: string[];
}

export interface GlobalNerRetention {
  total_unique_entities: number;
  found_in_global: number;
  retention_percent: number;
}

// ── Summaries ──

export interface SummarySection {
  section_idx: number;
  topic_hint: string;
  topic_generic: string;
  num_chunks: number;
  total_chars: number;
  summary: string;
  ner_retention?: NerRetention;
}

export interface SummariesResponse {
  book_name: string;
  method: string;
  model: string;
  model_l2?: string;
  created_at: string;
  total_sections: number;
  avg_ner_retention: number;
  global_ner_retention?: GlobalNerRetention;
  global_summary: string;
  sections: SummarySection[];
  /** Available model files when multiple summaries exist */
  available_models?: string[];
  /** Currently active model file name */
  current_model_file?: string;
}

// ── Settings ──

export interface OllamaSettings {
  host: string;
  port: string;
  model?: string;
  model_global?: string;
  embed_model?: string;
  ner_model?: string;
}

// ── Chunking Report ──

export interface SimilarityPair {
  chunk_a: number;
  chunk_b: number;
  topic_a: string;
  topic_b: string;
  similarity: number;
}

export interface SimilarityProfile {
  avg_intra: number | null;
  avg_boundary: number | null;
  avg_cross: number | null;
  n_intra: number;
  n_boundary: number;
  n_cross: number;
  intra: SimilarityPair[];
  boundary: SimilarityPair[];
  cross: SimilarityPair[];
}

export interface ComparisonRow {
  embed_chunk_id: number;
  embed_topic: string;
  embed_char: number;
  best_ner_chunk_id: number;
  ner_topic: string;
  ner_char: number;
  dist_chars: number;
  is_match: boolean;
}

export interface ChunkingReport {
  embed_total_chunks: number;
  embed_total_sections: number;
  ner_total_chunks: number;
  ner_total_sections: number;
  avg_jaccard_score: number | null;
  tolerance_chars: number;
  embed_similarity: SimilarityProfile;
  ner_similarity: SimilarityProfile;
  comparison: ComparisonRow[];
}

// ── Book Text ──

export interface BookTextData {
  book_name: string;
  preview: string;
  raw_preview: string;
  char_count: number;
  raw_char_count: number;
}

// ── Reader chunk (used internally by the reader view) ──

export interface ReaderChunk {
  text: string;
  entities: { word: string; label: string }[];
  char_start: number;
}

// ── NER section (used by reader NER mode) ──

export interface NerSection {
  sectionNum: number;
  label: string;
  parts: SemanticChunk[];
}

// ── Entity label constants ──

export const ENTITY_LABELS = ['PER', 'LOC', 'ORG', 'DATE', 'WORK', 'FANT', 'TIT', 'REL'] as const;
export type EntityLabel = typeof ENTITY_LABELS[number];

export const ENTITY_COLORS: Record<string, string> = {
  PER: '#fb7185', LOC: '#60a5fa', ORG: '#fbbf24',
  DATE: '#4ade80', WORK: '#c084fc', FANT: '#f472b6',
  TIT: '#2dd4bf', REL: '#f87171', EVENT: '#f59e0b'
};

export const ENTITY_CSS_CLASSES: Record<string, string> = {
  PER: 'ent-PER', LOC: 'ent-LOC', ORG: 'ent-ORG',
  DATE: 'ent-DATE', WORK: 'ent-WORK', FANT: 'ent-FANT',
  TIT: 'ent-TIT', REL: 'ent-REL', EVENT: 'ent-EVENT'
};

export const ENTITY_HL_CLASSES: Record<string, string> = {
  PER: 'hl-PER', LOC: 'hl-LOC', ORG: 'hl-ORG',
  DATE: 'hl-DATE', WORK: 'hl-WORK', FANT: 'hl-FANT',
  TIT: 'hl-TIT', REL: 'hl-REL', EVENT: 'hl-EVENT'
};

export const ENTITY_LABEL_NAMES: Record<string, string> = {
  PER: '👤 Persone', LOC: '📍 Luoghi', ORG: '🏛️ Org',
  DATE: '📅 Date', WORK: '📚 Opere', FANT: '✨ Fantastici',
  TIT: '🎖️ Titoli', REL: '⛪ Religiosi'
};
