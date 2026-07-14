import { Component, input, output, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import {
  Chapter, SemanticChunk, NerSection, ReaderChunk,
  ENTITY_LABELS, ENTITY_CSS_CLASSES, ENTITY_HL_CLASSES, ENTITY_LABEL_NAMES
} from '../../../models/models';
import { ApiService } from '../../../services/api.service';

@Component({
  selector: 'app-reader-view',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page-header" style="display:flex; align-items:center; justify-content:space-between;">
      <div>
        <h2>📖 {{ readerMethod === 'embed' ? 'Capitoli Semantici' : 'Sezioni NER' }}</h2>
        <p>Seleziona un capitolo e leggi il testo con le entità storiche evidenziate in colori</p>
      </div>
      <div style="display:flex; gap:0.5rem; align-items:center;">
        <select style="padding:0.5rem 0.75rem; font-size:0.85rem; border-radius:8px; border:1px solid var(--border); background:var(--bg-surface); color:var(--text-primary); cursor:pointer;"
                [(ngModel)]="readerMethod" (change)="switchReaderMethod()">
          <option value="embed">🔢 Metodo Embed (Capitoli)</option>
          <option value="ner">🏷️ Metodo NER (Sezioni)</option>
        </select>
        <button class="nav-btn" style="width:auto; padding:0.6rem 1rem; background:rgba(99,102,241,0.1); color:var(--accent); border:1px solid rgba(99,102,241,0.3);"
                (click)="onCompareClick.emit()">
          🔬 Confronta Metodi
        </button>
      </div>
    </div>
    <div class="reader-layout" style="flex:1; overflow:hidden;">
      <!-- Chapter list -->
      <div class="chapter-list">
        <input class="search-input" type="text" placeholder="🔎 Cerca capitolo..."
               [(ngModel)]="chapterSearch" style="font-size:0.78rem;padding:0.45rem 0.65rem;">
        <div *ngIf="loading() || readerLoading()" class="loading-state" style="padding:1rem;">⏳ Caricamento...</div>

        <!-- EMBED: capitoli reali -->
        <ng-container *ngIf="readerMethod === 'embed'">
          <div *ngFor="let ch of filteredChaptersForReader()"
               class="chapter-item"
               [class.active]="selectedReaderChapter()?.id === ch.id"
               (click)="selectReaderChapter(ch)">
            {{ ch.title || 'Capitolo ' + ch.chapter_id_num }}
          </div>
          <div *ngIf="!loading() && !chaptersData()?.length" class="empty-state" style="padding:1rem;">
            Nessun capitolo trovato. Esegui prima il chapter grouping.
          </div>
        </ng-container>

        <!-- NER: sezioni grezze -->
        <ng-container *ngIf="readerMethod === 'ner'">
          <div *ngFor="let sec of filteredNerSections()"
               class="chapter-item"
               [class.active]="selectedNerSection() === sec.sectionNum"
               (click)="selectNerSection(sec)">
            {{ sec.label }}
          </div>
          <div *ngIf="!loading() && !nerSections().length" class="empty-state" style="padding:1rem;">
            Sezioni NER non disponibili. Esegui il chunking NER dalla dashboard.
          </div>
        </ng-container>
      </div>

      <!-- Text content -->
      <div class="reader-content">
        <ng-container *ngIf="readerMethod === 'embed'">
          <div *ngIf="!selectedReaderChapter()" class="empty-state" style="padding:3rem;">
            ← Seleziona un capitolo dalla lista per leggere il testo
          </div>
          <ng-container *ngIf="selectedReaderChapter()">
            <h3>{{ selectedReaderChapter()!.title || 'Capitolo ' + selectedReaderChapter()!.chapter_id_num }}</h3>
            <div class="legend">
              <span *ngFor="let lbl of entityLabels" class="badge" [ngClass]="getEntClass(lbl)" style="pointer-events:none; font-size:0.72rem;">{{ labelName(lbl) }}</span>
            </div>
            <div class="entity-accordion" *ngIf="!readerLoading() && chapterEntities().length">
              <div class="accordion-header" (click)="entitiesOpen = !entitiesOpen">
                <span>🏷️ Entità di questo capitolo ({{ chapterEntities().length }} distinte)</span>
                <span>{{ entitiesOpen ? '▲' : '▼' }}</span>
              </div>
              <div class="accordion-body" *ngIf="entitiesOpen">
                <span *ngFor="let e of chapterEntities()" class="accordion-tag" [ngClass]="getEntClass(e.label)" [title]="e.label">
                  <span style="opacity:0.6;font-size:0.68rem;">{{ e.label }}</span> {{ e.word }}
                </span>
              </div>
            </div>
            <div *ngIf="readerLoading()" class="loading-state">⏳ Caricamento del capitolo...</div>
            <div *ngIf="!readerLoading()" [innerHTML]="renderedChapterHtml()" class="text-block"></div>
            <div *ngIf="!readerLoading() && chunkTexts().length === 0" class="empty-state">Nessun testo trovato per questo capitolo.</div>
          </ng-container>
        </ng-container>

        <ng-container *ngIf="readerMethod === 'ner'">
          <div *ngIf="selectedNerSection() === null" class="empty-state" style="padding:3rem;">
            ← Seleziona una sezione dalla lista per leggere il testo
          </div>
          <ng-container *ngIf="selectedNerSection() !== null">
            <h3>{{ nerSections()[selectedNerSection()!]?.label }}</h3>
            <div class="legend">
              <span *ngFor="let lbl of entityLabels" class="badge" [ngClass]="getEntClass(lbl)" style="pointer-events:none; font-size:0.72rem;">{{ labelName(lbl) }}</span>
            </div>
            <div class="entity-accordion" *ngIf="!readerLoading() && chapterEntities().length">
              <div class="accordion-header" (click)="entitiesOpen = !entitiesOpen">
                <span>🏷️ Entità di questa sezione ({{ chapterEntities().length }} distinte)</span>
                <span>{{ entitiesOpen ? '▲' : '▼' }}</span>
              </div>
              <div class="accordion-body" *ngIf="entitiesOpen">
                <span *ngFor="let e of chapterEntities()" class="accordion-tag" [ngClass]="getEntClass(e.label)" [title]="e.label">
                  <span style="opacity:0.6;font-size:0.68rem;">{{ e.label }}</span> {{ e.word }}
                </span>
              </div>
            </div>
            <div *ngIf="readerLoading()" class="loading-state">⏳ Caricamento...</div>
            <div *ngIf="!readerLoading()" [innerHTML]="renderedChapterHtml()" class="text-block"></div>
            <div *ngIf="!readerLoading() && chunkTexts().length === 0" class="empty-state">Nessun testo trovato per questa sezione.</div>
          </ng-container>
        </ng-container>
      </div>
    </div>
  `
})
export class ReaderViewComponent {
  chaptersData = input<Chapter[] | null>(null);
  bookId = input<number>(0);
  loading = input<boolean>(false);
  onCompareClick = output<void>();

  readerMethod: 'embed' | 'ner' = 'embed';
  readerLoading = signal(false);
  selectedReaderChapter = signal<Chapter | null>(null);
  selectedNerSection = signal<number | null>(null);
  nerSections = signal<NerSection[]>([]);
  chunkTexts = signal<ReaderChunk[]>([]);
  chapterSearch = '';
  entitiesOpen = false;

  readonly entityLabels = [...ENTITY_LABELS];

  constructor(
    private api: ApiService,
    private sanitizer: DomSanitizer
  ) {}

  filteredChaptersForReader = computed(() => {
    const chapters = this.chaptersData() || [];
    const q = this.chapterSearch.toLowerCase().trim();
    if (!q) return chapters;
    return chapters.filter(c => (c.title || '').toLowerCase().includes(q) || String(c.chapter_id_num).includes(q));
  });

  filteredNerSections = computed(() => {
    const secs = this.nerSections();
    const q = this.chapterSearch.toLowerCase().trim();
    if (!q) return secs;
    return secs.filter(s => s.label.toLowerCase().includes(q));
  });

  chapterEntities = computed(() => {
    const chunks = this.chunkTexts();
    const seen = new Set<string>();
    const result: {word: string; label: string}[] = [];
    chunks.forEach(chunk => {
      (chunk.entities || []).forEach((e: any) => {
        const key = `${e.label}:${e.word}`;
        if (!seen.has(key)) { seen.add(key); result.push({word: e.word, label: e.label}); }
      });
    });
    return result.sort((a, b) => a.label.localeCompare(b.label) || a.word.localeCompare(b.word));
  });

  renderedChapterHtml = computed((): SafeHtml => {
    const chunks = this.chunkTexts();
    if (!chunks.length) return this.sanitizer.bypassSecurityTrustHtml('');

    let html = '';
    chunks.forEach((chunk, i) => {
      const text = chunk.text;
      const entities: {label: string; word: string}[] = chunk.entities || [];

      const seenWords = new Set<string>();
      const uniqueEntities = entities
        .filter(e => { if (seenWords.has(e.word)) return false; seenWords.add(e.word); return true; })
        .sort((a, b) => b.word.length - a.word.length);

      const intervals: {start: number; end: number; label: string; word: string}[] = [];
      for (const ent of uniqueEntities) {
        const w = ent.word;
        let idx = 0;
        while (true) {
          const pos = text.indexOf(w, idx);
          if (pos === -1) break;
          intervals.push({ start: pos, end: pos + w.length, label: ent.label, word: w });
          idx = pos + 1;
        }
      }

      intervals.sort((a, b) => a.start - b.start || b.word.length - a.word.length);
      const clean: typeof intervals = [];
      let cursor = 0;
      for (const s of intervals) {
        if (s.start >= cursor) { clean.push(s); cursor = s.end; }
      }

      let chunkHtml = '';
      let pos = 0;
      for (const s of clean) {
        if (s.start > pos) chunkHtml += this._escapeHtml(text.slice(pos, s.start));
        const cls = this.getHlClass(s.label);
        chunkHtml += `<span class="${cls}" title="${s.label}">${this._escapeHtml(s.word)}</span>`;
        pos = s.end;
      }
      if (pos < text.length) chunkHtml += this._escapeHtml(text.slice(pos));

      html += chunkHtml;
      if (i < chunks.length - 1) html += '\n\n';
    });

    return this.sanitizer.bypassSecurityTrustHtml(html.replace(/\n/g, '<br>'));
  });

  switchReaderMethod() {
    this.selectedReaderChapter.set(null);
    this.selectedNerSection.set(null);
    this.chunkTexts.set([]);
    this.entitiesOpen = false;
    if (this.readerMethod === 'ner' && !this.nerSections().length) {
      this.loadNerSections();
    }
  }

  loadNerSections() {
    this.readerLoading.set(true);
    this.api.getSemanticChunks(this.bookId(), 'ner').subscribe({
      next: (chunks: SemanticChunk[]) => {
        const groups = new Map<number, NerSection>();
        for (const c of chunks) {
          const m = (c.topic_hint || '').match(/(\d+)/);
          const secNum = m ? parseInt(m[1]) : c.chunk_id;
          if (!groups.has(secNum)) {
            groups.set(secNum, { sectionNum: secNum, label: '', parts: [] });
          }
          groups.get(secNum)!.parts.push(c);
        }
        const sorted = Array.from(groups.values()).sort((a, b) => a.sectionNum - b.sectionNum);
        sorted.forEach((s, i) => { s.label = `Capitolo ${i + 1}`; });
        this.nerSections.set(sorted);
        this.readerLoading.set(false);
      },
      error: () => {
        this.nerSections.set([]);
        this.readerLoading.set(false);
      }
    });
  }

  selectNerSection(sec: NerSection) {
    this.selectedNerSection.set(sec.sectionNum);
    this.entitiesOpen = false;
    this.chunkTexts.set(sec.parts.map((c: any) => ({
      text: c.text,
      entities: c.entities || [],
      char_start: c.char_start ?? 0
    })));
  }

  selectReaderChapter(ch: Chapter) {
    if (this.selectedReaderChapter()?.id === ch.id) return;
    this.selectedReaderChapter.set(ch);
    this.entitiesOpen = false;
    this.readerLoading.set(true);
    this.chunkTexts.set([]);
    this.api.getChapterChunks(this.bookId(), ch.chapter_id_num).subscribe({
      next: (chunks: any[]) => {
        this.chunkTexts.set(chunks.map((c: any) => ({
          text: c.text,
          entities: c.entities || [],
          char_start: c.char_start ?? 0
        })));
        this.readerLoading.set(false);
      },
      error: () => { this.readerLoading.set(false); }
    });
  }

  getEntClass(label: string): string {
    return ENTITY_CSS_CLASSES[label] ?? 'ent-default';
  }

  getHlClass(label: string): string {
    return ENTITY_HL_CLASSES[label] ?? '';
  }

  labelName(label: string): string {
    return ENTITY_LABEL_NAMES[label] ?? label;
  }

  _escapeHtml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
}
