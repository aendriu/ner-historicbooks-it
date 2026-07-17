import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  Book, NerResult, Chapter, SemanticChunk,
  SummariesResponse, BookTextData, ChunkingReport
} from '../models/models';

/** Base URL for the FastAPI backend */
const API_BASE = 'http://localhost:8000/api';

@Injectable({ providedIn: 'root' })
export class ApiService {

  /** Returns the user-configured Ollama base URL from localStorage */
  getOllamaUrl(): string {
    return localStorage.getItem('OLLAMA_BASE_URL') || '';
  }

  constructor(private http: HttpClient) {}

  // ── Books ──

  /** Fetch all books */
  getBooks(): Observable<Book[]> {
    return this.http.get<Book[]>(`${API_BASE}/books`);
  }

  /** Fetch a single book by ID */
  getBook(id: number): Observable<Book> {
    return this.http.get<Book>(`${API_BASE}/books/${id}`);
  }

  /** Upload a book file (.json / .txt) */
  uploadBook(file: File): Observable<{ book_id: number }> {
    const fd = new FormData();
    fd.append('file', file);
    return this.http.post<{ book_id: number }>(`${API_BASE}/books/upload`, fd);
  }

  /** Download book export as ZIP blob */
  exportBook(id: number): Observable<Blob> {
    return this.http.get(`${API_BASE}/books/${id}/export`, { responseType: 'blob' });
  }

  // ── Pipeline steps ──

  /** Run the full pipeline (clean → NER → chunking → summaries) */
  runAll(id: number): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${API_BASE}/books/${id}/run/all`, {});
  }

  /** Run OCR cleanup phase only */
  runClean(id: number): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${API_BASE}/books/${id}/run/clean`, {});
  }

  /** Run NER extraction phase only */
  runNer(id: number): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${API_BASE}/books/${id}/run/ner`, {});
  }

  /** Run semantic chunking (embed or NER method) */
  runChunking(id: number, method: 'embed' | 'ner' = 'embed'): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${API_BASE}/books/${id}/run/chunking`, { method });
  }

  /** Run summarization phase */
  runSummarize(id: number, method: 'embed' | 'ner' = 'embed'): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${API_BASE}/books/${id}/run/summarize`, { method });
  }

  /** Fetch summaries for a book, optionally filtered by method and model */
  getSummaries(id: number, method: 'embed' | 'ner' = 'embed', model?: string): Observable<SummariesResponse> {
    const params = model ? `?method=${method}&model=${encodeURIComponent(model)}` : `?method=${method}`;
    return this.http.get<SummariesResponse>(`${API_BASE}/books/${id}/summaries${params}`);
  }

  /** Cancel a running summarization job */
  cancelSummarize(): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${API_BASE}/run/summarize/cancel`, {});
  }

  // ── Progress ──

  /** Poll progress for a specific phase */
  getProgress(id: number, phase: string): Observable<{ status: string; logs: string[] }> {
    return this.http.get<{ status: string; logs: string[] }>(`${API_BASE}/books/${id}/progress/${phase}`);
  }

  // ── Data retrieval ──

  /** Fetch raw + cleaned text for a book */
  getBookText(id: number): Observable<BookTextData> {
    return this.http.get<BookTextData>(`${API_BASE}/books/${id}/text`);
  }

  /** Fetch NER results for a book */
  getNer(id: number): Observable<NerResult> {
    return this.http.get<NerResult>(`${API_BASE}/books/${id}/ner`);
  }

  /** Fetch all semantic chunks for a book */
  getChunks(id: number): Observable<{ total: number; chunks: SemanticChunk[] }> {
    return this.http.get<{ total: number; chunks: SemanticChunk[] }>(`${API_BASE}/books/${id}/chunks`);
  }

  /** Fetch detected chapters for a book */
  getChapters(id: number): Observable<Chapter[]> {
    return this.http.get<Chapter[]>(`${API_BASE}/books/${id}/chapters`);
  }

  /** Fetch the global summary text for a book */
  getBookGlobalSummary(id: number): Observable<{ content: string | null }> {
    return this.http.get<{ content: string | null }>(`${API_BASE}/books/${id}/global-summary`);
  }

  /** Fetch semantic chunks belonging to a specific chapter */
  getChapterChunks(bookId: number, chapterId: number): Observable<SemanticChunk[]> {
    return this.http.get<SemanticChunk[]>(`${API_BASE}/books/${bookId}/chapters/${chapterId}/chunks`);
  }

  /** Fetch summary for a specific chapter */
  getChapterSummary(bookId: number, chapterId: number): Observable<{ content: string; level: number }> {
    return this.http.get<{ content: string; level: number }>(`${API_BASE}/books/${bookId}/chapters/${chapterId}/summary`);
  }

  // ── Settings ──

  /** Get current Ollama settings from backend */
  getOllamaSettings(): Observable<{ host: string; port: string }> {
    return this.http.get<{ host: string; port: string }>(`${API_BASE}/settings/ollama`);
  }

  /** Save Ollama settings to backend */
  setOllamaSettings(host: string, port: string): Observable<{ status: string; message?: string; host?: string; port?: string; missing_models?: string[]; installed_models?: string[] }> {
    return this.http.post<{ status: string; message?: string; host?: string; port?: string; missing_models?: string[]; installed_models?: string[] }>(`${API_BASE}/settings/ollama`, { host, port });
  }

  /** Fetch the chunking comparison report (embed vs NER) */
  getChunkingReport(bookId: number): Observable<ChunkingReport> {
    return this.http.get<ChunkingReport>(`${API_BASE}/books/${bookId}/chunking-report`);
  }

  /** Fetch semantic chunks by method (embed or NER) */
  getSemanticChunks(bookId: number, method: 'embed' | 'ner'): Observable<SemanticChunk[]> {
    return this.http.get<SemanticChunk[]>(`${API_BASE}/books/${bookId}/semantic-chunks?method=${method}`);
  }
}
