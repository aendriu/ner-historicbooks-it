import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

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

export interface NerResult {
  book_name: string;
  total_entities: number;
  entities: { word: string; label: string; score: number; start: number; end: number }[];
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private base = 'http://localhost:8000/api';

  constructor(private http: HttpClient) {}

  // ── Books ──
  getBooks(): Observable<Book[]> {
    return this.http.get<Book[]>(`${this.base}/books`);
  }

  getBook(id: number): Observable<Book> {
    return this.http.get<Book>(`${this.base}/books/${id}`);
  }

  uploadBook(file: File): Observable<{ book_id: number }> {
    const fd = new FormData();
    fd.append('file', file);
    return this.http.post<{ book_id: number }>(`${this.base}/books/upload`, fd);
  }

  exportBook(id: number): Observable<Blob> {
    return this.http.get(`${this.base}/books/${id}/export`, { responseType: 'blob' });
  }

  // ── Pipeline steps ──
  runAll(id: number): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/books/${id}/run/all`, {});
  }

  runClean(id: number): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/books/${id}/run/clean`, {});
  }

  runNer(id: number): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/books/${id}/run/ner`, {});
  }

  runChunking(id: number, method: 'embed' | 'ner' = 'embed'): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/books/${id}/run/chunking`, { method });
  }

  runChapters(id: number): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/books/${id}/run/chapters`, {});
  }

  runSummaries(id: number): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/books/${id}/run/summaries`, {});
  }

  // ── Progress ──
  getProgress(id: number, phase: string): Observable<{ status: string; logs: string[] }> {
    return this.http.get<{ status: string; logs: string[] }>(`${this.base}/books/${id}/progress/${phase}`);
  }

  // ── Data retrieval ──
  getBookText(id: number): Observable<any> {
    return this.http.get<any>(`${this.base}/books/${id}/text`);
  }

  getNer(id: number): Observable<NerResult> {
    return this.http.get<NerResult>(`${this.base}/books/${id}/ner`);
  }

  getChunks(id: number): Observable<{ total: number; chunks: SemanticChunk[] }> {
    return this.http.get<{ total: number; chunks: SemanticChunk[] }>(`${this.base}/books/${id}/chunks`);
  }

  getChapters(id: number): Observable<Chapter[]> {
    return this.http.get<Chapter[]>(`${this.base}/books/${id}/chapters`);
  }

  getChapterChunks(bookId: number, chapterId: number): Observable<SemanticChunk[]> {
    return this.http.get<SemanticChunk[]>(`${this.base}/books/${bookId}/chapters/${chapterId}/chunks`);
  }

  getSummaries(id: number): Observable<any[]> {
    return this.http.get<any[]>(`${this.base}/books/${id}/summaries`);
  }

  getChapterSummary(bookId: number, chapterId: number): Observable<{ content: string; level: number }> {
    return this.http.get<{ content: string; level: number }>(`${this.base}/books/${bookId}/chapters/${chapterId}/summary`);
  }

  // ── Settings ──
  getOllamaSettings(): Observable<{ host: string; port: string }> {
    return this.http.get<{ host: string; port: string }>(`${this.base}/settings/ollama`);
  }

  setOllamaSettings(host: string, port: string): Observable<{ status: string; message?: string; host?: string; port?: string }> {
    return this.http.post<{ status: string; message?: string; host?: string; port?: string }>(`${this.base}/settings/ollama`, { host, port });
  }

  getChunkingReport(bookId: number): Observable<any> {
    return this.http.get<any>(`${this.base}/books/${bookId}/chunking-report`);
  }

  getSemanticChunks(bookId: number, method: 'embed' | 'ner'): Observable<any[]> {
    return this.http.get<any[]>(`${this.base}/books/${bookId}/semantic-chunks?method=${method}`);
  }
}
