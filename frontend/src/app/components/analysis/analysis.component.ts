import { Component, OnInit, signal, effect, computed, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ApiService, NerResult, Chapter } from '../../services/api.service';
import { BookStateService } from '../../services/book-state.service';
import { Chart, registerables } from 'chart.js';

Chart.register(...registerables);

@Component({
  selector: 'app-analysis',
  standalone: true,
  imports: [CommonModule, FormsModule],
  styles: [`
    :host { display: block; height: 100vh; background: var(--bg-base); }

    /* ── Layout ── */
    .layout-wrapper {
      display: flex; flex-direction: row;
      width: 100vw; height: 100vh; overflow: hidden;
    }
    .sidebar {
      width: 260px; flex-shrink: 0;
      background: var(--bg-surface);
      border-right: 1px solid var(--border);
      display: flex; flex-direction: column;
      padding: 1.25rem; gap: 0.5rem;
      height: 100vh; overflow-y: auto;
    }
    .main { flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

    /* ── Sidebar nav buttons ── */
    .nav-btn {
      width: 100%; padding: 0.85rem 1rem;
      border-radius: 10px; font-weight: 600; font-size: 0.85rem;
      cursor: pointer; transition: all 0.18s;
      background: transparent; color: var(--text-muted);
      border: 1px solid transparent; text-align: left;
      display: flex; align-items: center; gap: 0.6rem;
    }
    .nav-btn:hover { background: var(--bg-base); color: var(--text-primary); }
    .nav-btn.active {
      background: rgba(99,102,241,0.12); color: var(--accent);
      border-color: rgba(99,102,241,0.3);
    }
    .nav-btn .icon { font-size: 1.1rem; }

    /* ── Page header ── */
    .page-header {
      padding: 1.5rem 2rem 1rem;
      border-bottom: 1px solid var(--border);
      background: var(--bg-surface); flex-shrink: 0;
    }
    .page-header h2 { font-size: 1.25rem; font-weight: 700; color: var(--text-primary); margin: 0; }
    .page-header p { font-size: 0.82rem; color: var(--text-muted); margin: 0.25rem 0 0; }

    /* ── Scroll area ── */
    .scroll-area { flex: 1; overflow-y: auto; padding: 1.5rem 2rem; }

    /* ── Stat cards ── */
    .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
    .stat-card {
      background: var(--bg-surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 1.1rem 1.25rem;
    }
    .stat-card .label { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }
    .stat-card .value { font-size: 1.5rem; font-weight: 700; color: var(--text-primary); margin-top: 0.2rem; }
    .stat-card .value.green { color: #4ade80; }
    .stat-card .value.red { color: #f87171; }
    .stat-card .value.blue { color: #60a5fa; }
    .stat-card .value.purple { color: var(--accent); }

    /* ── OCR diff panel ── */
    .diff-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
    .diff-panel {
      background: var(--bg-surface); border: 1px solid var(--border);
      border-radius: 12px; overflow: hidden; display: flex; flex-direction: column;
      max-height: 60vh;
    }
    .diff-panel-header {
      padding: 0.75rem 1rem; font-size: 0.8rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border);
    }
    .diff-panel-header.dirty { color: #f87171; background: rgba(248,113,113,0.06); }
    .diff-panel-header.clean { color: #4ade80; background: rgba(74,222,128,0.06); }
    .diff-panel pre {
      flex: 1; overflow-y: auto; padding: 1rem;
      font-size: 0.82rem; line-height: 1.7; white-space: pre-wrap;
      color: var(--text-primary); font-family: 'Inter', sans-serif;
      margin: 0;
    }

    /* ── NER chart area ── */
    .ner-grid { display: grid; grid-template-columns: 300px 1fr; gap: 1rem; margin-bottom: 1.5rem; }
    .card {
      background: var(--bg-surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 1.25rem; overflow: hidden;
    }
    .card h3 { font-size: 0.85rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin: 0 0 1rem; }

    /* ── Entity badges ── */
    .badge {
      display: inline-flex; align-items: center; gap: 0.3rem;
      padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.78rem; font-weight: 600;
      cursor: pointer; border: 1px solid transparent; transition: all 0.15s;
    }
    .badge:hover { opacity: 0.8; }
    .badge.selected { box-shadow: 0 0 0 2px currentColor; }
    .ent-PER { color: #fb7185; background: rgba(251,113,133,0.15); }
    .ent-LOC { color: #60a5fa; background: rgba(96,165,250,0.15); }
    .ent-ORG { color: #fbbf24; background: rgba(251,191,36,0.15); }
    .ent-DATE { color: #4ade80; background: rgba(74,222,128,0.15); }
    .ent-WORK { color: #c084fc; background: rgba(192,132,252,0.15); }
    .ent-FANT { color: #f472b6; background: rgba(244,114,182,0.15); }
    .ent-default { color: #94a3b8; background: rgba(148,163,184,0.15); }

    /* bar item for top entities */
    .bar-item { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; }
    .bar-item .word { font-size: 0.82rem; font-weight: 600; color: var(--text-primary); min-width: 120px; }
    .bar-track { flex: 1; background: var(--bg-base); border-radius: 4px; height: 8px; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
    .bar-item .count { font-size: 0.78rem; color: var(--text-muted); min-width: 28px; text-align: right; }

    /* entity chip list */
    .chip-list { display: flex; flex-wrap: wrap; gap: 0.4rem; }
    .ent-chip {
      display: inline-flex; flex-direction: column; gap: 0.15rem;
      padding: 0.4rem 0.65rem; border-radius: 8px; border: 1px solid currentColor;
      font-size: 0.78rem; cursor: pointer; transition: opacity 0.15s;
    }
    .ent-chip:hover { opacity: 0.75; }

    /* Accordion entity panel */
    .entity-accordion {
      border: 1px solid var(--border); border-radius: 10px;
      overflow: hidden; margin-bottom: 1.25rem;
    }
    .accordion-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.75rem 1rem; background: var(--bg-surface);
      cursor: pointer; user-select: none; font-size: 0.85rem; font-weight: 600;
      color: var(--text-primary);
    }
    .accordion-header:hover { background: var(--bg-base); }
    .accordion-body {
      padding: 0.75rem 1rem;
      display: flex; flex-wrap: wrap; gap: 0.4rem;
      background: var(--bg-base); border-top: 1px solid var(--border);
    }
    .accordion-tag {
      display: inline-flex; align-items: center; gap: 0.35rem;
      padding: 0.2rem 0.55rem; border-radius: 20px;
      font-size: 0.76rem; font-weight: 600; border: 1px solid currentColor;
    }

    /* ── Reader layout for chapters + summaries ── */
    .reader-layout { display: flex; height: 100%; overflow: hidden; }
    .chapter-list {
      width: 240px; flex-shrink: 0; border-right: 1px solid var(--border);
      overflow-y: auto; background: var(--bg-surface); padding: 0.75rem;
    }
    .chapter-item {
      padding: 0.6rem 0.75rem; border-radius: 8px; cursor: pointer;
      font-size: 0.82rem; font-weight: 500; color: var(--text-muted);
      transition: all 0.15s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .chapter-item:hover { background: var(--bg-base); color: var(--text-primary); }
    .chapter-item.active { background: rgba(99,102,241,0.12); color: var(--accent); font-weight: 700; }
    .reader-content { flex: 1; overflow-y: auto; padding: 2rem; }
    .reader-content h3 { font-size: 1.3rem; font-weight: 700; color: var(--text-primary); margin: 0 0 1.25rem; }
    .text-block {
      font-size: 0.9rem; line-height: 1.9; color: var(--text-primary);
      font-family: 'Georgia', 'Times New Roman', serif;
      white-space: pre-wrap; margin-bottom: 2rem;
    }

    /* ── Inline entity highlights ── */
    .hl-PER { background: rgba(251,113,133,0.2); color: #fb7185; border-radius: 3px; padding: 0 2px; }
    .hl-LOC { background: rgba(96,165,250,0.2); color: #60a5fa; border-radius: 3px; padding: 0 2px; }
    .hl-ORG { background: rgba(251,191,36,0.2); color: #d97706; border-radius: 3px; padding: 0 2px; }
    .hl-DATE { background: rgba(74,222,128,0.2); color: #16a34a; border-radius: 3px; padding: 0 2px; }
    .hl-WORK { background: rgba(192,132,252,0.2); color: #c084fc; border-radius: 3px; padding: 0 2px; }
    .hl-FANT { background: rgba(244,114,182,0.2); color: #f472b6; border-radius: 3px; padding: 0 2px; }

    /* ── Summary cards ── */
    .summary-card {
      background: var(--bg-surface); border: 1px solid var(--border);
      border-radius: 14px; padding: 1.75rem; margin-bottom: 1.25rem;
    }
    .summary-card h3 {
      font-size: 1rem; font-weight: 700; color: var(--accent);
      border-bottom: 1px solid var(--border); padding-bottom: 0.75rem; margin: 0 0 1rem;
    }
    .summary-card .summary-text {
      font-size: 0.88rem; line-height: 1.85; color: var(--text-primary);
      font-family: 'Georgia', serif; white-space: pre-wrap;
    }
    .summary-card .no-summary {
      font-size: 0.82rem; color: var(--text-muted); font-style: italic;
    }

    /* ── Legend ── */
    .legend { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
    .loading-state { display: flex; align-items: center; gap: 0.5rem; color: var(--accent); font-weight: 600; padding: 2rem; }
    .empty-state { color: var(--text-muted); font-size: 0.85rem; font-style: italic; padding: 1rem 0; }

    /* ── NER filter bar ── */
    .filter-bar { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1rem; }
    .filter-btn {
      padding: 0.3rem 0.7rem; border-radius: 20px; font-size: 0.78rem; font-weight: 600;
      cursor: pointer; border: 1px solid var(--border); background: var(--bg-surface);
      color: var(--text-muted); transition: all 0.15s;
    }
    .filter-btn:hover { border-color: var(--accent); color: var(--accent); }
    .filter-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }

    /* ── Search input ── */
    .search-input {
      width: 100%; padding: 0.6rem 0.85rem; border-radius: 8px;
      border: 1px solid var(--border); background: var(--bg-base);
      color: var(--text-primary); font-size: 0.85rem; margin-bottom: 0.75rem;
      outline: none;
    }
    .search-input:focus { border-color: var(--accent); }

    /* ── Modal ── */
    .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 100; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(4px); }
    .modal-content { background: var(--bg-base); border-radius: 16px; width: 600px; max-width: 90vw; box-shadow: 0 10px 25px rgba(0,0,0,0.2); border: 1px solid var(--border); overflow: hidden; display: flex; flex-direction: column; }
    .modal-header { padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: var(--bg-surface); }
    .modal-header h3 { margin: 0; font-size: 1.1rem; color: var(--text-primary); }
    .close-btn { background: none; border: none; font-size: 1.2rem; cursor: pointer; color: var(--text-muted); }
    .close-btn:hover { color: var(--text-primary); }
    .modal-body { padding: 1.5rem; max-height: 70vh; overflow-y: auto; }
  `],
  template: `
  <div class="layout-wrapper">

    <!-- ── SIDEBAR ── -->
    <aside class="sidebar">
      <button class="nav-btn mb-2" style="color: var(--text-muted); font-size: 0.8rem;" (click)="goBack()">
        ← Torna alla Dashboard
      </button>

      <div style="font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); padding: 0.25rem 0.5rem; margin-top: 0.5rem;">Analisi</div>

      <button class="nav-btn" [class.active]="view() === 'ocr'" (click)="view.set('ocr')">
        <span class="icon">🔍</span> Pulizia OCR
      </button>
      <button class="nav-btn" [class.active]="view() === 'ner'" (click)="view.set('ner')">
        <span class="icon">🏷️</span> Entità (NER)
      </button>
      <button class="nav-btn" [class.active]="view() === 'reader'" (click)="view.set('reader')">
        <span class="icon">📖</span> Capitoli Semantici
      </button>
      <button class="nav-btn" [class.active]="view() === 'summaries'" (click)="view.set('summaries')">
        <span class="icon">📝</span> Riassunti
      </button>
      <button class="nav-btn" [class.active]="view() === 'compare'" (click)="view.set('compare'); loadReport()">
        <span class="icon">🔬</span> Confronta Metodi
      </button>
    </aside>

    <!-- ── MAIN ── -->
    <main class="main">

      <!-- ════ VIEW: OCR ════ -->
      <ng-container *ngIf="view() === 'ocr'">
        <div class="page-header">
          <h2>🔍 Analisi Pulizia OCR</h2>
          <p>Confronto tra il testo grezzo caricato e quello dopo la pulizia tramite AI</p>
        </div>
        <div class="scroll-area">
          <div *ngIf="loading()" class="loading-state">⏳ Caricamento...</div>

          <ng-container *ngIf="!loading() && textData()">
            <!-- Stats -->
            <div class="stat-grid">
              <div class="stat-card">
                <div class="label">Caratteri originali</div>
                <div class="value blue">{{ textData().raw_char_count | number }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Caratteri dopo pulizia</div>
                <div class="value green">{{ textData().char_count | number }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Caratteri rimossi</div>
                <div class="value red">{{ (textData().raw_char_count - textData().char_count) | number }}</div>
              </div>
              <div class="stat-card">
                <div class="label">% Pulizia</div>
                <div class="value purple">
                  {{ ((textData().raw_char_count - textData().char_count) / textData().raw_char_count * 100 | number:'1.1-1') }}%
                </div>
              </div>
            </div>

            <!-- Side-by-side diff -->
            <div class="diff-grid">
              <div class="diff-panel">
                <div class="diff-panel-header dirty">❌ Testo Grezzo (OCR raw)</div>
                <pre>{{ textData().raw_preview }}</pre>
              </div>
              <div class="diff-panel">
                <div class="diff-panel-header clean">✅ Testo Pulito</div>
                <pre>{{ textData().preview }}</pre>
              </div>
            </div>
          </ng-container>
        </div>
      </ng-container>

      <!-- ════ VIEW: NER ════ -->
      <ng-container *ngIf="view() === 'ner'">
        <div class="page-header">
          <h2>🏷️ Entità Storiche (NER)</h2>
          <p>{{ nerData()?.total_entities | number }} entità estratte dal testo. Filtra per tipo per esplorare.</p>
        </div>
        <div class="scroll-area">
          <div *ngIf="loading()" class="loading-state">⏳ Caricamento...</div>

          <ng-container *ngIf="!loading() && nerData()?.entities?.length">
            <!-- Charts row -->
            <div class="ner-grid" style="height: 280px; margin-bottom: 1.5rem;">
              <div class="card" style="display:flex;flex-direction:column;">
                <h3>Distribuzione Tipi</h3>
                <div style="flex:1;position:relative;"><canvas #pieCanvas></canvas></div>
              </div>
              <div class="card" style="overflow-y:auto;">
                <h3>Top 15 Entità più Citate</h3>
                <div *ngFor="let ent of topEntities()" class="bar-item">
                  <span class="word">
                    <span class="badge" [ngClass]="getEntClass(ent.label)" style="pointer-events:none;">{{ ent.label }}</span>
                    {{ ent.word }}
                  </span>
                  <div class="bar-track">
                    <div class="bar-fill" [ngClass]="getEntClass(ent.label)"
                         [style.width.%]="(ent.count / topEntities()[0].count) * 100"
                         [style.background]="getEntColor(ent.label)">
                    </div>
                  </div>
                  <span class="count">{{ ent.count }}</span>
                </div>
              </div>
            </div>

            <!-- Filter bar + search -->
            <div class="card">
              <div class="filter-bar">
                <button class="filter-btn" [class.active]="selectedLabel() === null" (click)="selectedLabel.set(null)">
                  Tutte ({{ nerData()?.total_entities | number }})
                </button>
                <button class="filter-btn" *ngFor="let lbl of labelStats()"
                  [class.active]="selectedLabel() === lbl.label"
                  (click)="selectedLabel.set(lbl.label)">
                  {{ lbl.label }} ({{ lbl.count }})
                </button>
              </div>
              <input class="search-input" type="text" placeholder="🔎 Cerca entità..." [(ngModel)]="searchQuery">
              <div class="chip-list">
                <div *ngFor="let f of filteredInstances().slice(0, 200)"
                     class="ent-chip" [ngClass]="getEntClass(f.label)">
                  <span style="font-weight:700;">{{ f.word }}</span>
                  <span style="font-size:10px; opacity:0.7;">{{ f.label }} • {{ f.count }}x</span>
                </div>
                <div *ngIf="filteredInstances().length === 0" class="empty-state">Nessuna entità trovata.</div>
              </div>
            </div>
          </ng-container>

          <div *ngIf="!loading() && !nerData()?.entities?.length" class="empty-state">
            Nessuna entità disponibile. Esegui prima la fase NER.
          </div>
        </div>
      </ng-container>

      <!-- ════ VIEW: READER (Capitoli veri + NER in-line) ════ -->
      <ng-container *ngIf="view() === 'reader'">
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
                    (click)="view.set('compare'); loadReport()">
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
                  <span *ngFor="let lbl of ['PER','LOC','ORG','DATE','WORK','FANT','TIT','REL']" class="badge" [ngClass]="getEntClass(lbl)" style="pointer-events:none; font-size:0.72rem;">{{ labelName(lbl) }}</span>
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
                  <span *ngFor="let lbl of ['PER','LOC','ORG','DATE','WORK','FANT','TIT','REL']" class="badge" [ngClass]="getEntClass(lbl)" style="pointer-events:none; font-size:0.72rem;">{{ labelName(lbl) }}</span>
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
      </ng-container>


      <!-- ════ VIEW: SUMMARIES ════ -->
      <ng-container *ngIf="view() === 'summaries'">
        <div class="page-header">
          <h2>📝 Riassunti Semantici</h2>
          <p>Riassunti narrativi generati da AI per ogni sezione semantica. La NER retention misura quante entità chiave sopravvivono nel riassunto.</p>
        </div>

        <!-- Sinossi globale: barra collassabile + modal fullscreen -->
        <div *ngIf="bookGlobalSummary()" style="margin: 0 1rem 0.75rem 1rem; flex-shrink: 0;">
          <!-- Barra compatta cliccabile -->
          <div (click)="globalSummaryExpanded.set(true)"
               style="display:flex; align-items:center; justify-content:space-between;
                      padding: 0.65rem 1rem; border-radius: 10px; cursor: pointer;
                      border: 1px solid rgba(99,102,241,0.35);
                      background: rgba(99,102,241,0.06);
                      transition: background 0.15s;"
               onmouseenter="this.style.background='rgba(99,102,241,0.12)'"
               onmouseleave="this.style.background='rgba(99,102,241,0.06)'">
            <span style="color:#6366f1; font-weight:700; font-size:0.9rem;">📖 Sinossi Globale — Livello 0</span>
            <span style="color:#6366f1; font-size:0.8rem; opacity:0.75;">Espandi ↗</span>
          </div>
        </div>

        <!-- Modal fullscreen sinossi -->
        <div *ngIf="globalSummaryExpanded()" style="
             position:fixed; inset:0; z-index:2000;
             background:rgba(0,0,0,0.55); backdrop-filter:blur(6px);
             display:flex; align-items:center; justify-content:center;
             padding: 2rem;"
             (click)="globalSummaryExpanded.set(false)">
          <div (click)="$event.stopPropagation()"
               style="background:var(--bg-surface); border:1px solid rgba(99,102,241,0.4);
                      border-radius:16px; width:100%; max-width:820px; max-height:85vh;
                      display:flex; flex-direction:column; box-shadow:0 20px 60px rgba(0,0,0,0.4);">
            <!-- Header modal -->
            <div style="display:flex; align-items:center; justify-content:space-between;
                        padding:1.25rem 1.5rem; border-bottom:1px solid var(--border); flex-shrink:0;">
              <h3 style="color:#6366f1; margin:0; font-size:1.1rem;">📖 Sinossi Globale — Livello 0</h3>
              <button (click)="globalSummaryExpanded.set(false)"
                      style="background:transparent; border:none; color:var(--text-muted);
                             font-size:1.4rem; cursor:pointer; line-height:1; padding:0.25rem 0.5rem;
                             border-radius:6px; transition:background 0.15s;"
                      onmouseenter="this.style.background='var(--bg-base)'"
                      onmouseleave="this.style.background='transparent'">✕</button>
            </div>
            <!-- Testo scrollabile -->
            <div style="overflow-y:auto; padding:1.5rem; flex:1;">
              <p style="font-size:0.95rem; line-height:1.8; color:var(--text-primary);
                        white-space:pre-wrap; margin:0;">{{ bookGlobalSummary() }}</p>
            </div>
          </div>
        </div>



        <div *ngIf="!summariesData()" class="empty-state" style="padding:3rem;text-align:center;">
          <p style="font-size:1.1rem;margin-bottom:0.5rem;">📭 Nessun riassunto disponibile</p>
          <p style="font-size:0.85rem;color:var(--text-muted);">Avvia la fase <strong>Riassunti</strong> dalla Dashboard, poi ricarica questa pagina.</p>
        </div>

        <div *ngIf="summariesData()" class="reader-layout" style="flex:1; min-height:0; overflow:hidden;">
          <!-- Section nav -->
          <div class="chapter-list">
            <input class="search-input" type="text" placeholder="🔎 Cerca sezione..."
                   [(ngModel)]="summarySearch" style="font-size:0.78rem;padding:0.45rem 0.65rem;">
            <div *ngFor="let sec of filteredSummarySections()"
                 class="chapter-item"
                 [class.active]="selectedSummarySection()?.section_idx === sec.section_idx"
                 (click)="selectedSummarySection.set(sec)">
              <span [style.opacity]="sec.summary ? '1' : '0.4'">
                {{ sec.summary ? '✅' : '○' }}
              </span>
              {{ sec.topic_hint || 'Sezione ' + sec.section_idx }}
            </div>
          </div>

          <!-- Summary content -->
          <div class="reader-content">
            <div *ngIf="!selectedSummarySection()" class="empty-state" style="padding:3rem;">
              ← Seleziona una sezione per leggere il suo riassunto
            </div>
            <ng-container *ngIf="selectedSummarySection() as sec">
              <h3>{{ sec.topic_hint || 'Sezione ' + sec.section_idx }}</h3>
              <p style="font-size:0.78rem;color:var(--text-muted);margin-bottom:1rem;">
                {{ sec.num_chunks }} chunk · {{ sec.total_chars | number }} caratteri
                <span *ngIf="sec.ner_retention" style="margin-left:1rem;">
                  🏷️ NER retention: <strong style="color:var(--accent)">{{ sec.ner_retention.retention_percent }}%</strong>
                </span>
              </p>
              <div class="summary-card" *ngIf="sec.summary">
                <p class="summary-text">{{ sec.summary }}</p>
              </div>
              <div *ngIf="!sec.summary" class="summary-card">
                <p class="no-summary">Nessun riassunto generato per questa sezione.</p>
              </div>

              <!-- Entità perse -->
              <div *ngIf="sec.ner_retention?.lost?.length" style="margin-top:1rem;padding:0.75rem;border-radius:8px;background:rgba(239,68,68,0.05);border:1px solid rgba(239,68,68,0.2);">
                <p style="font-size:0.78rem;color:#ef4444;margin:0;">
                  ⚠️ Entità perse nel riassunto: {{ sec.ner_retention.lost.join(', ') }}
                </p>
              </div>

              <!-- Navigation -->
              <div style="display:flex;gap:1rem;margin-top:1rem;">
                <button (click)="prevSummarySection()" [disabled]="selectedSummarySectionIndex() === 0"
                  style="padding:0.5rem 1rem;border-radius:8px;border:1px solid var(--border);background:var(--bg-surface);color:var(--text-primary);cursor:pointer;font-weight:600;">
                  ← Precedente
                </button>
                <button (click)="nextSummarySection()" [disabled]="selectedSummarySectionIndex() >= (summariesData()?.sections?.length - 1)"
                  style="padding:0.5rem 1rem;border-radius:8px;border:1px solid var(--border);background:var(--bg-surface);color:var(--text-primary);cursor:pointer;font-weight:600;">
                  Successivo →
                </button>
              </div>
            </ng-container>
          </div>
        </div>
      </ng-container>

      <!-- ════ VIEW: CONFRONTO METODI ════ -->
      <ng-container *ngIf="view() === 'compare'">
        <div class="page-header">
          <h2>🔬 Confronto Scientifico dei Metodi di Chunking</h2>
          <p>Analisi quantitativa: Metodo Embed (cosine similarity) vs Metodo NER (sovrapposizione entità). Dati richiesti dalla tesi.</p>
        </div>
        <div class="scroll-area">
          <div *ngIf="reportLoading()" class="loading-state">⏳ Calcolo metriche in corso...</div>

          <ng-container *ngIf="!reportLoading() && reportData()">

            <!-- ── Sezione 1: Statistiche riepilogative ── -->
            <h3 style="font-size:0.9rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin:0 0 .75rem">1 · Riepilogo strutturale</h3>
            <div class="stat-grid" style="grid-template-columns:repeat(5,1fr);margin-bottom:2rem">
              <div class="stat-card">
                <div class="label">Chunk totali Embed</div>
                <div class="value blue">{{ reportData().embed_total_chunks ?? 'N/D' }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Sezioni Embed</div>
                <div class="value blue">{{ reportData().embed_total_sections ?? 'N/D' }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Chunk totali NER</div>
                <div class="value purple">{{ reportData().ner_total_chunks ?? 'N/D' }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Sezioni NER</div>
                <div class="value purple">{{ reportData().ner_total_sections ?? 'N/D' }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Confini Embed confermati da NER</div>
                <div class="value" [class.green]="reportData().avg_jaccard_score >= 0.6" [class.red]="reportData().avg_jaccard_score < 0.4">
                  {{ reportData().avg_jaccard_score !== null ? (reportData().avg_jaccard_score * 100).toFixed(1) + '%' : 'N/D' }}
                </div>
                <div style="font-size:0.68rem;color:var(--text-muted);margin-top:.2rem">su {{ reportData().embed_total_sections ?? 0 }} confini Embed</div>
              </div>
            </div>

            <!-- ── Sezione 2: Profilo di Similarità Coseno ── -->
            <h3 style="font-size:0.9rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin:0 0 .75rem">2 · Profilo di coerenza testuale (TF-IDF cosine similarity)</h3>
            <div class="diff-grid" style="margin-bottom:2rem">
              <!-- Embed -->
              <div class="card" *ngIf="reportData().embed_similarity">
                <h3>🔢 Metodo Embed</h3>
                <div class="stat-grid" style="grid-template-columns:1fr 1fr 1fr;margin-bottom:.75rem">
                  <div class="stat-card">
                    <div class="label">Sim. intra-sezione</div>
                    <div class="value green">{{ reportData().embed_similarity.avg_intra !== null ? reportData().embed_similarity.avg_intra.toFixed(3) : '—' }}</div>
                  </div>
                  <div class="stat-card">
                    <div class="label">Sim. al confine</div>
                    <div class="value red">{{ reportData().embed_similarity.avg_boundary !== null ? reportData().embed_similarity.avg_boundary.toFixed(3) : '—' }}</div>
                  </div>
                  <div class="stat-card">
                    <div class="label">Sim. cross-sezione</div>
                    <div class="value red">{{ reportData().embed_similarity.avg_cross !== null ? reportData().embed_similarity.avg_cross.toFixed(3) : '—' }}</div>
                  </div>
                </div>
                <p style="font-size:0.78rem;color:var(--text-muted);line-height:1.5;margin:0">
                  Un buon metodo mostra: <strong style="color:#4ade80">intra alta</strong> · <strong style="color:#f87171">al confine bassa</strong> · <strong style="color:#f87171">cross bassissima</strong>.
                  Il Δ = intra − confine misura la "nitidezza" del taglio.
                  <br><strong>Δ Embed = {{ reportData().embed_similarity.avg_intra !== null && reportData().embed_similarity.avg_boundary !== null ? (reportData().embed_similarity.avg_intra - reportData().embed_similarity.avg_boundary).toFixed(3) : '—' }}</strong>
                  <span style="opacity:0.6">· {{ reportData().embed_similarity.n_intra }} coppie intra · {{ reportData().embed_similarity.n_boundary }} al confine · {{ reportData().embed_similarity.n_cross }} cross</span>
                </p>
              </div>
              <!-- NER -->
              <div class="card" *ngIf="reportData().ner_similarity">
                <h3>🏷️ Metodo NER</h3>
                <div class="stat-grid" style="grid-template-columns:1fr 1fr 1fr;margin-bottom:.75rem">
                  <div class="stat-card">
                    <div class="label">Sim. intra-sezione</div>
                    <div class="value green">{{ reportData().ner_similarity.avg_intra !== null ? reportData().ner_similarity.avg_intra.toFixed(3) : '—' }}</div>
                  </div>
                  <div class="stat-card">
                    <div class="label">Sim. al confine</div>
                    <div class="value red">{{ reportData().ner_similarity.avg_boundary !== null ? reportData().ner_similarity.avg_boundary.toFixed(3) : '—' }}</div>
                  </div>
                  <div class="stat-card">
                    <div class="label">Sim. cross-sezione</div>
                    <div class="value red">{{ reportData().ner_similarity.avg_cross !== null ? reportData().ner_similarity.avg_cross.toFixed(3) : '—' }}</div>
                  </div>
                </div>
                <p style="font-size:0.78rem;color:var(--text-muted);line-height:1.5;margin:0">
                  <strong>Δ NER = {{ reportData().ner_similarity.avg_intra !== null && reportData().ner_similarity.avg_boundary !== null ? (reportData().ner_similarity.avg_intra - reportData().ner_similarity.avg_boundary).toFixed(3) : '—' }}</strong>
                  — Il metodo con Δ maggiore segmenta in modo più netto.
                  <span style="opacity:0.6">· {{ reportData().ner_similarity.n_intra }} coppie intra · {{ reportData().ner_similarity.n_boundary }} al confine · {{ reportData().ner_similarity.n_cross }} cross</span>
                </p>
              </div>
            </div>

            <!-- ── Sezione 3: Tabella Boundary Agreement ── -->
            <h3 style="font-size:0.9rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin:0 0 .75rem">3 · Corrispondenza confini Embed ↔ NER (tolleranza ±{{ reportData().tolerance_chars }} car.)</h3>
            <div class="card" style="overflow-x:auto;margin-bottom:2rem;padding:0">
              <table style="width:100%;border-collapse:collapse;font-size:0.8rem">
                <thead>
                  <tr style="background:var(--bg-base);">
                    <th style="padding:.6rem .9rem;text-align:left;font-weight:700;color:var(--text-muted);border-bottom:1px solid var(--border)">#Embed</th>
                    <th style="padding:.6rem .9rem;text-align:left;font-weight:700;color:var(--text-muted);border-bottom:1px solid var(--border)">Topic Embed</th>
                    <th style="padding:.6rem .9rem;text-align:right;font-weight:700;color:var(--text-muted);border-bottom:1px solid var(--border)">Char Embed</th>
                    <th style="padding:.6rem .9rem;text-align:left;font-weight:700;color:var(--text-muted);border-bottom:1px solid var(--border)">#NER</th>
                    <th style="padding:.6rem .9rem;text-align:left;font-weight:700;color:var(--text-muted);border-bottom:1px solid var(--border)">Topic NER</th>
                    <th style="padding:.6rem .9rem;text-align:right;font-weight:700;color:var(--text-muted);border-bottom:1px solid var(--border)">Char NER</th>
                    <th style="padding:.6rem .9rem;text-align:right;font-weight:700;color:var(--text-muted);border-bottom:1px solid var(--border)">Distanza</th>
                    <th style="padding:.6rem .9rem;text-align:center;font-weight:700;color:var(--text-muted);border-bottom:1px solid var(--border)">Match</th>
                  </tr>
                </thead>
                <tbody>
                  <tr *ngFor="let row of reportData().comparison"
                      [style.background]="row.is_match ? 'rgba(74,222,128,0.04)' : 'rgba(248,113,113,0.04)'">
                    <td style="padding:.55rem .9rem;color:var(--text-muted)">{{ row.embed_chunk_id }}</td>
                    <td style="padding:.55rem .9rem;color:var(--text-primary)">{{ row.embed_topic }}</td>
                    <td style="padding:.55rem .9rem;text-align:right;color:var(--text-muted);font-variant-numeric:tabular-nums">{{ row.embed_char | number }}</td>
                    <td style="padding:.55rem .9rem;color:var(--text-muted)">{{ row.best_ner_chunk_id }}</td>
                    <td style="padding:.55rem .9rem;color:var(--text-primary)">{{ row.ner_topic }}</td>
                    <td style="padding:.55rem .9rem;text-align:right;color:var(--text-muted);font-variant-numeric:tabular-nums">{{ row.ner_char | number }}</td>
                    <td style="padding:.55rem .9rem;text-align:right;font-variant-numeric:tabular-nums" [style.color]="row.dist_chars > reportData().tolerance_chars ? '#f87171' : '#4ade80'">{{ row.dist_chars | number }}</td>
                    <td style="padding:.55rem .9rem;text-align:center">{{ row.is_match ? '✅' : '❌' }}</td>
                  </tr>
                </tbody>
              </table>
              <div *ngIf="!reportData().comparison?.length" class="empty-state" style="padding:1rem">Esegui entrambi i metodi di chunking per visualizzare la tabella.</div>
            </div>

            <!-- ── Sezione 4: Esempi di coppie ── -->
            <h3 style="font-size:0.9rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin:0 0 .75rem">4 · Esempi di coppie (Metodo Embed)</h3>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-bottom:2rem">
              <!-- Intra -->
              <div class="card">
                <h3 style="color:#4ade80">✅ Intra-sezione (alta similarità attesa)</h3>
                <div *ngFor="let e of reportData().embed_similarity?.intra?.slice(0,5)" style="margin-bottom:.6rem;padding:.5rem;background:var(--bg-base);border-radius:8px;font-size:0.78rem">
                  <div style="color:var(--text-muted);margin-bottom:.2rem">Chunk {{ e.chunk_a }} → {{ e.chunk_b }}</div>
                  <div style="color:var(--text-primary);font-weight:600">{{ e.topic_a }}</div>
                  <div style="display:flex;align-items:center;gap:.5rem;margin-top:.3rem">
                    <div style="flex:1;background:var(--border);border-radius:4px;height:6px"><div [style.width.%]="e.similarity*100" style="background:#4ade80;height:6px;border-radius:4px"></div></div>
                    <span style="color:#4ade80;font-weight:700;min-width:42px">{{ e.similarity.toFixed(3) }}</span>
                  </div>
                </div>
              </div>
              <!-- Boundary -->
              <div class="card">
                <h3 style="color:#fb7185">🔀 Al confine semantico (bassa similarità attesa)</h3>
                <div *ngFor="let e of reportData().embed_similarity?.boundary?.slice(0,5)" style="margin-bottom:.6rem;padding:.5rem;background:var(--bg-base);border-radius:8px;font-size:0.78rem">
                  <div style="color:var(--text-muted);margin-bottom:.2rem">Chunk {{ e.chunk_a }} → {{ e.chunk_b }}</div>
                  <div style="color:var(--text-primary);font-weight:600">{{ e.topic_a }} ↦ {{ e.topic_b }}</div>
                  <div style="display:flex;align-items:center;gap:.5rem;margin-top:.3rem">
                    <div style="flex:1;background:var(--border);border-radius:4px;height:6px"><div [style.width.%]="e.similarity*100" style="background:#fb7185;height:6px;border-radius:4px"></div></div>
                    <span style="color:#fb7185;font-weight:700;min-width:42px">{{ e.similarity.toFixed(3) }}</span>
                  </div>
                </div>
              </div>
              <!-- Cross -->
              <div class="card">
                <h3 style="color:#f87171">↔ Cross-sezione (bassissima attesa)</h3>
                <div *ngFor="let e of reportData().embed_similarity?.cross?.slice(0,5)" style="margin-bottom:.6rem;padding:.5rem;background:var(--bg-base);border-radius:8px;font-size:0.78rem">
                  <div style="color:var(--text-muted);margin-bottom:.2rem">Chunk {{ e.chunk_a }} ↔ {{ e.chunk_b }}</div>
                  <div style="color:var(--text-primary);font-weight:600">{{ e.topic_a }} ↦ {{ e.topic_b }}</div>
                  <div style="display:flex;align-items:center;gap:.5rem;margin-top:.3rem">
                    <div style="flex:1;background:var(--border);border-radius:4px;height:6px"><div [style.width.%]="e.similarity*100" style="background:#f87171;height:6px;border-radius:4px"></div></div>
                    <span style="color:#f87171;font-weight:700;min-width:42px">{{ e.similarity.toFixed(3) }}</span>
                  </div>
                </div>
              </div>
            </div>

          </ng-container>

          <div *ngIf="!reportLoading() && !reportData()" class="empty-state">
            ❌ Esegui prima il chunking con entrambi i metodi (Embed e NER) dalla dashboard del libro.
          </div>
        </div>
      </ng-container>

    </main>
  </div>
  `
})
export class AnalysisComponent implements OnInit {
  @ViewChild('pieCanvas') pieCanvas?: ElementRef<HTMLCanvasElement>;
  chartInstance: any;

  view = signal<'ocr' | 'ner' | 'reader' | 'summaries' | 'compare'>('ocr');
  loading = signal(true);
  readerLoading = signal(false);

  textData = signal<any>(null);
  nerData = signal<NerResult | null>(null);
  chaptersData = signal<Chapter[] | null>(null);
  bookGlobalSummary = signal<string | null>(null);

  // Nuovo sistema riassunti (JSON file-based)
  summariesData = signal<any>(null);
  selectedSummarySection = signal<any>(null);
  globalSummaryExpanded = signal(false);

  selectedLabel = signal<string | null>(null);
  selectedChapter = signal<Chapter | null>(null);
  selectedSummaryChapter = signal<Chapter | null>(null);
  
  selectedReaderChapter = signal<Chapter | null>(null);
  readerMethod: 'embed' | 'ner' = 'embed';

  // NER mode state
  nerSections = signal<{ sectionNum: number; label: string; parts: any[] }[]>([]);
  selectedNerSection = signal<number | null>(null);

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
      next: (chunks: any[]) => {
        const groups = new Map<number, { sectionNum: number; label: string; parts: any[] }>();
        for (const c of chunks) {
          const m = (c.topic_hint || '').match(/(\d+)/);
          const secNum = m ? parseInt(m[1]) : c.chunk_id;
          if (!groups.has(secNum)) {
            groups.set(secNum, { sectionNum: secNum, label: '', parts: [] });
          }
          groups.get(secNum)!.parts.push(c);
        }
        // Ordina e rinomina progressivamente come "Capitolo 1, 2, ..."
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

  selectNerSection(sec: { sectionNum: number; label: string; parts: any[] }) {
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

  searchQuery = '';
  chapterSearch = '';
  summarySearch = '';

  // Accordion state
  entitiesOpen = false;

  bookId = signal<number>(0);

  // chunk texts for reader
  chunkTexts = signal<{text: string; entities: any[]; char_start: number}[]>([]);

  // Report confronto metodi
  showReport = signal(false);
  reportLoading = signal(false);
  reportData = signal<any>(null);


  // ── Computed ──

  topEntities = computed(() => {
    const data = this.nerData();
    if (!data?.entities) return [];
    const wordCounts: Record<string, {count: number, label: string}> = {};
    data.entities.forEach(e => {
      const w = e.word.trim();
      if (!wordCounts[w]) wordCounts[w] = { count: 0, label: e.label };
      wordCounts[w].count++;
    });
    return Object.entries(wordCounts)
      .map(([word, v]) => ({word, count: v.count, label: v.label}))
      .sort((a, b) => b.count - a.count)
      .slice(0, 15);
  });

  labelStats = computed(() => {
    const data = this.nerData();
    if (!data?.entities) return [];
    const counts: Record<string, number> = {};
    data.entities.forEach(e => { counts[e.label] = (counts[e.label] || 0) + 1; });
    return Object.entries(counts)
      .map(([label, count]) => ({label, count}))
      .sort((a, b) => b.count - a.count);
  });

  filteredInstances = computed(() => {
    const label = this.selectedLabel();
    const data = this.nerData();
    if (!data?.entities) return [];
    const q = this.searchQuery.toLowerCase().trim();
    const wordInfo: Record<string, {count: number, label: string}> = {};
    data.entities.forEach(e => {
      if (label !== null && e.label !== label) return;
      const w = e.word.trim();
      if (q && !w.toLowerCase().includes(q)) return;
      if (!wordInfo[w]) wordInfo[w] = { count: 0, label: e.label };
      wordInfo[w].count++;
    });
    return Object.entries(wordInfo)
      .map(([word, info]) => ({word, count: info.count, label: info.label}))
      .sort((a, b) => b.count - a.count);
  });

  filteredSummaryChapters = computed(() => {
    const chapters = this.chaptersData() || [];
    const q = this.summarySearch.toLowerCase().trim();
    if (!q) return chapters;
    return chapters.filter(c => (c.title || '').toLowerCase().includes(q));
  });

  // Computed per il nuovo sistema sezioni
  filteredSummarySections = computed(() => {
    const sections: any[] = this.summariesData()?.sections || [];
    const q = this.summarySearch.toLowerCase().trim();
    if (!q) return sections;
    return sections.filter((s: any) =>
      (s.topic_hint || '').toLowerCase().includes(q)
    );
  });

  selectedSummarySectionIndex = computed(() => {
    const sel = this.selectedSummarySection();
    if (!sel) return -1;
    return (this.summariesData()?.sections || []).findIndex(
      (s: any) => s.section_idx === sel.section_idx
    );
  });

  selectedSummaryChapterIndex = computed(() => {
    const ch = this.selectedSummaryChapter();
    if (!ch) return -1;
    return (this.chaptersData() || []).findIndex(c => c.id === ch.id);
  });

  // Unique entities for current chapter (deduplicated by word+label)
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

      // Deduplicate entities by word (longest first to avoid partial matches)
      const seenWords = new Set<string>();
      const uniqueEntities = entities
        .filter(e => { if (seenWords.has(e.word)) return false; seenWords.add(e.word); return true; })
        .sort((a, b) => b.word.length - a.word.length); // longest first

      // Find all occurrences of each entity word in the text
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

      // Sort by start, remove overlaps (keep first/longest)
      intervals.sort((a, b) => a.start - b.start || b.word.length - a.word.length);
      const clean: typeof intervals = [];
      let cursor = 0;
      for (const s of intervals) {
        if (s.start >= cursor) { clean.push(s); cursor = s.end; }
      }

      // Build HTML
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

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private api: ApiService,
    private state: BookStateService,
    private sanitizer: DomSanitizer
  ) {
    // Render chart when switching to NER view
    effect(() => {
      const v = this.view();
      const ner = this.nerData();
      if (v === 'ner' && ner) {
        setTimeout(() => this.renderChart(), 100);
      }
    });
  }

  ngOnInit() {
    this.route.paramMap.subscribe(params => {
      const id = Number(params.get('id'));
      this.bookId.set(id);
      if (id) this.loadData(id);
    });
  }

  loadData(bookId: number) {
    this.loading.set(true);
    let loaded = 0;
    const done = () => { if (++loaded === 4) this.loading.set(false); };

    this.api.getBookText(bookId).subscribe({ next: d => { this.textData.set(d); done(); }, error: done });
    this.api.getNer(bookId).subscribe({ next: d => { this.nerData.set(d); done(); }, error: () => { this.nerData.set(null); done(); } });
    this.api.getChapters(bookId).subscribe({ next: d => { this.chaptersData.set(d); done(); }, error: () => { this.chaptersData.set(null); done(); } });
    // Carica i nuovi riassunti file-based
    this.api.getSummaries(bookId, 'embed').subscribe({
      next: d => {
        this.summariesData.set(d);
        this.bookGlobalSummary.set(d.global_summary || null);
        // Preseleziona prima sezione
        if (d.sections?.length) this.selectedSummarySection.set(d.sections[0]);
        done();
      },
      error: () => { this.summariesData.set(null); this.bookGlobalSummary.set(null); done(); }
    });
  }

  selectChapter(ch: Chapter) {
    this.selectedChapter.set(ch);
    this.loadChapterChunks(ch);
  }

  loadChapterChunks(ch: Chapter) {
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

  _escapeHtml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  prevSummary() {
    const idx = this.selectedSummaryChapterIndex();
    const chapters = this.chaptersData() || [];
    if (idx > 0) this.selectedSummaryChapter.set(chapters[idx - 1]);
  }

  nextSummary() {
    const idx = this.selectedSummaryChapterIndex();
    const chapters = this.chaptersData() || [];
    if (idx < chapters.length - 1) this.selectedSummaryChapter.set(chapters[idx + 1]);
  }

  prevSummarySection() {
    const idx = this.selectedSummarySectionIndex();
    const sections = this.summariesData()?.sections || [];
    if (idx > 0) this.selectedSummarySection.set(sections[idx - 1]);
  }

  nextSummarySection() {
    const idx = this.selectedSummarySectionIndex();
    const sections = this.summariesData()?.sections || [];
    if (idx < sections.length - 1) this.selectedSummarySection.set(sections[idx + 1]);
  }

  renderChart() {
    if (!this.pieCanvas) return;
    if (this.chartInstance) this.chartInstance.destroy();
    const stats = this.labelStats();
    const colors = stats.map(s => this.getEntColor(s.label));
    this.chartInstance = new Chart(this.pieCanvas.nativeElement, {
      type: 'doughnut',
      data: {
        labels: stats.map(s => s.label),
        datasets: [{ data: stats.map(s => s.count), backgroundColor: colors, borderWidth: 2, borderColor: 'transparent' }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } } }
    });
  }

  getEntClass(label: string) {
    const m: Record<string, string> = { PER:'ent-PER', LOC:'ent-LOC', ORG:'ent-ORG', DATE:'ent-DATE', WORK:'ent-WORK', FANT:'ent-FANT', TIT:'ent-TIT', REL:'ent-REL', EVENT:'ent-EVENT' };
    return m[label] ?? 'ent-default';
  }
  getHlClass(label: string) {
    const m: Record<string, string> = { PER:'hl-PER', LOC:'hl-LOC', ORG:'hl-ORG', DATE:'hl-DATE', WORK:'hl-WORK', FANT:'hl-FANT', TIT:'hl-TIT', REL:'hl-REL', EVENT:'hl-EVENT' };
    return m[label] ?? '';
  }
  getEntColor(label: string) {
    const m: Record<string, string> = { PER:'#fb7185', LOC:'#60a5fa', ORG:'#fbbf24', DATE:'#4ade80', WORK:'#c084fc', FANT:'#f472b6', TIT:'#2dd4bf', REL:'#f87171', EVENT:'#f59e0b' };
    return m[label] ?? '#94a3b8';
  }
  labelName(label: string): string {
    const m: Record<string,string> = { PER:'👤 Persone', LOC:'📍 Luoghi', ORG:'🏛️ Org', DATE:'📅 Date', WORK:'📚 Opere', FANT:'✨ Fantastici', TIT:'🎖️ Titoli', REL:'⛪ Religiosi' };
    return m[label] ?? label;
  }

  goBack() { this.router.navigate(['/']); }

  loadReport() {
    this.showReport.set(true);
    this.reportLoading.set(true);
    this.api.getChunkingReport(this.bookId()).subscribe({
      next: (data) => { this.reportData.set(data); this.reportLoading.set(false); },
      error: () => { this.reportData.set(null); this.reportLoading.set(false); }
    });
  }
}
