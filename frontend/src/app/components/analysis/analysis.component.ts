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

      <!-- ════ VIEW: READER (Testo + NER in-line) ════ -->
      <ng-container *ngIf="view() === 'reader'">
        <div class="page-header" style="display:flex; align-items:center; justify-content:space-between;">
          <div>
            <h2>📖 Capitoli Semantici</h2>
            <p>Seleziona un capitolo e leggi il testo con le entità storiche evidenziate in colori</p>
          </div>
          <div style="display:flex; gap:0.5rem; align-items:center;">
            <select class="w-input" style="width: auto; padding: 0.5rem; font-size: 0.85rem;" [(ngModel)]="selectedReaderMethod" (change)="loadSemanticChunksForReader()">
              <option value="embed">🔢 Metodo Embed</option>
              <option value="ner">🏷️ Metodo NER</option>
            </select>
            <button class="nav-btn" style="width:auto; padding:0.6rem 1rem; background:rgba(99,102,241,0.1); color:var(--accent); border:1px solid rgba(99,102,241,0.3);"
                    (click)="loadReport()">
              🔬 Confronta Metodi
            </button>
          </div>
        </div>
        <div class="reader-layout" style="flex:1; overflow:hidden;">
          <!-- Chapter list gerarchico -->
          <div class="chapter-list">
            <input class="search-input" type="text" placeholder="🔎 Cerca capitolo..."
                   [(ngModel)]="chapterSearch" style="font-size:0.78rem;padding:0.45rem 0.65rem;">

            <ng-container *ngFor="let group of groupedSemanticChunks()">
              <!-- Voce capitolo -->
              <div class="chapter-item"
                   [class.active]="selectedSectionNum() === group.sectionNum"
                   style="display:flex; align-items:center; justify-content:space-between; gap:0.5rem;"
                   (click)="selectSemanticSection(group)">
                <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                  📂 {{ group.label }}
                </span>
                <!-- Chevron espandi solo se ci sono più parti -->
                <span *ngIf="group.parts.length > 1"
                      style="font-size:0.75rem; opacity:0.6; cursor:pointer; flex-shrink:0;"
                      (click)="$event.stopPropagation(); toggleSection(group.sectionNum)">
                  {{ isSectionExpanded(group.sectionNum) ? '▲' : '▼' }}
                  <span style="font-size:0.68rem;">({{ group.parts.length }})</span>
                </span>
              </div>

              <!-- Sotto-voci parti (visibili solo se espanso e ci sono più parti) -->
              <ng-container *ngIf="group.parts.length > 1 && isSectionExpanded(group.sectionNum)">
                <div *ngFor="let part of group.parts; let pi = index"
                     class="chapter-item"
                     [class.active]="selectedSemanticChunk()?.chunk_id === part.chunk_id && selectedSectionNum() === group.sectionNum"
                     style="padding-left:1.75rem; font-size:0.78rem; opacity:0.85;"
                     (click)="selectSemanticChunk(part)">
                  └ Parte {{ pi + 1 }}
                </div>
              </ng-container>
            </ng-container>
          </div>

          <!-- Text content -->
          <div class="reader-content">
            <div *ngIf="!selectedSemanticChunk()" class="empty-state" style="padding:3rem;">
              ← Seleziona un capitolo/sezione dalla lista per leggere il testo
            </div>
            <ng-container *ngIf="selectedSemanticChunk()">
              <ng-container *ngFor="let group of groupedSemanticChunks()">
                <ng-container *ngIf="group.sectionNum === selectedSectionNum()">
                  <h3>
                    {{ group.label }}
                    <span *ngIf="group.parts.length > 1 && chunkTexts().length === 1"
                          style="font-size:0.8rem; font-weight:400; color:var(--text-muted);">
                      — Parte {{ group.parts.indexOf(selectedSemanticChunk()) + 1 }} di {{ group.parts.length }}
                    </span>
                  </h3>
                </ng-container>
              </ng-container>

              <!-- Legend -->
              <div class="legend">
                <span *ngFor="let lbl of ['PER','LOC','ORG','DATE','WORK','FANT','TIT','REL']" class="badge" [ngClass]="getEntClass(lbl)" style="pointer-events:none; font-size:0.72rem;">
                  {{ labelName(lbl) }}
                </span>
              </div>

              <!-- Collapsible entity list -->
              <div class="entity-accordion" *ngIf="!readerLoading() && chapterEntities().length">
                <div class="accordion-header" (click)="entitiesOpen = !entitiesOpen">
                  <span>🏷️ Entità di questo capitolo ({{ chapterEntities().length }} distinte)</span>
                  <span>{{ entitiesOpen ? '▲' : '▼' }}</span>
                </div>
                <div class="accordion-body" *ngIf="entitiesOpen">
                  <span *ngFor="let e of chapterEntities()"
                        class="accordion-tag" [ngClass]="getEntClass(e.label)"
                        [title]="e.label">
                    <span style="opacity:0.6;font-size:0.68rem;">{{ e.label }}</span>
                    {{ e.word }}
                  </span>
                </div>
              </div>

              <div *ngIf="readerLoading()" class="loading-state">⏳ Caricamento del capitolo...</div>
              <div *ngIf="!readerLoading()" [innerHTML]="renderedChapterHtml()" class="text-block"></div>
              
              <div *ngIf="!readerLoading() && chunkTexts().length === 0" class="empty-state">Nessun testo trovato per questo capitolo.</div>
            </ng-container>
          </div>
        </div>
      </ng-container>


      <!-- ════ VIEW: SUMMARIES ════ -->
      <ng-container *ngIf="view() === 'summaries'">
        <div class="page-header">
          <h2>📝 Riassunti per Capitolo</h2>
          <p>Riassunti narrativi generati da AI per ogni capitolo del libro. Scorri per validare la comprensione del modello.</p>
        </div>
        <div class="reader-layout" style="flex:1;overflow:hidden;">
          <!-- Chapter nav -->
          <div class="chapter-list">
            <input class="search-input" type="text" placeholder="🔎 Cerca capitolo..."
                   [(ngModel)]="summarySearch" style="font-size:0.78rem;padding:0.45rem 0.65rem;">
            <div *ngFor="let ch of filteredSummaryChapters()"
                 class="chapter-item"
                 [class.active]="selectedSummaryChapter()?.id === ch.id"
                 (click)="selectedSummaryChapter.set(ch)">
              <span [style.opacity]="ch.summaries.length ? '1' : '0.4'">
                {{ ch.summaries.length ? '✅' : '○' }}
              </span>
              {{ ch.title || 'Cap. ' + ch.chapter_id_num }}
            </div>
          </div>

          <!-- Summary content -->
          <div class="reader-content">
            <div *ngIf="!selectedSummaryChapter()" class="empty-state" style="padding:3rem;">
              ← Seleziona un capitolo per leggere il suo riassunto
            </div>
            <ng-container *ngIf="selectedSummaryChapter()">
              <h3>{{ selectedSummaryChapter()!.title || 'Capitolo ' + selectedSummaryChapter()!.chapter_id_num }}</h3>
              <div class="summary-card" *ngIf="selectedSummaryChapter()!.summaries.length">
                <p class="summary-text">{{ selectedSummaryChapter()!.summaries[0].content }}</p>
              </div>
              <div *ngIf="!selectedSummaryChapter()!.summaries.length" class="summary-card">
                <p class="no-summary">Nessun riassunto generato per questo capitolo. Completa la fase "Genera Riassunti" dalla Dashboard.</p>
              </div>

              <!-- Navigation -->
              <div style="display:flex;gap:1rem;margin-top:1rem;">
                <button (click)="prevSummary()" [disabled]="selectedSummaryChapterIndex() === 0"
                  style="padding:0.5rem 1rem;border-radius:8px;border:1px solid var(--border);background:var(--bg-surface);color:var(--text-primary);cursor:pointer;font-weight:600;">
                  ← Precedente
                </button>
                <button (click)="nextSummary()" [disabled]="selectedSummaryChapterIndex() === chaptersData()!.length - 1"
                  style="padding:0.5rem 1rem;border-radius:8px;border:1px solid var(--border);background:var(--bg-surface);color:var(--text-primary);cursor:pointer;font-weight:600;">
                  Successivo →
                </button>
              </div>
            </ng-container>
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

  view = signal<'ocr' | 'ner' | 'reader' | 'summaries'>('ocr');
  loading = signal(true);
  readerLoading = signal(false);

  textData = signal<any>(null);
  nerData = signal<NerResult | null>(null);
  chaptersData = signal<Chapter[] | null>(null);

  selectedLabel = signal<string | null>(null);
  selectedChapter = signal<Chapter | null>(null);
  selectedSummaryChapter = signal<Chapter | null>(null);
  
  // Semantic chunks logic for reader
  selectedReaderMethod = 'embed';
  semanticChunks = signal<any[]>([]);
  selectedSemanticChunk = signal<any>(null);
  semanticChunksLoaded = false;

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

  // Sezioni espanse nella sidebar dei capitoli semantici
  expandedSections = new Set<number>();
  selectedSectionNum = signal<number | null>(null);

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

  filteredSemanticChunks = computed(() => {
    const chunks = this.semanticChunks() || [];
    const q = this.chapterSearch.toLowerCase().trim();
    if (!q) return chunks;
    return chunks.filter(c => (c.topic_hint || '').toLowerCase().includes(q) ||
      String(c.chunk_id).includes(q));
  });

  // Raggruppa i chunk per numero di sezione semantica
  groupedSemanticChunks = computed(() => {
    const chunks = this.filteredSemanticChunks();
    const groups = new Map<number, { sectionNum: number; label: string; parts: any[] }>();
    for (const c of chunks) {
      const m = (c.topic_hint || '').match(/(\d+)/);
      const secNum = m ? parseInt(m[1]) : c.chunk_id;
      if (!groups.has(secNum)) {
        const baseLabel = (c.topic_hint || `Sezione ${secNum}`).replace(/ \(parte\)/, '');
        groups.set(secNum, { sectionNum: secNum, label: baseLabel, parts: [] });
      }
      groups.get(secNum)!.parts.push(c);
    }
    return Array.from(groups.values());
  });

  filteredSummaryChapters = computed(() => {
    const chapters = this.chaptersData() || [];
    const q = this.summarySearch.toLowerCase().trim();
    if (!q) return chapters;
    return chapters.filter(c => (c.title || '').toLowerCase().includes(q));
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

    // Load semantic chunks when switching to reader view
    effect(() => {
      if (this.view() === 'reader' && !this.semanticChunksLoaded) {
        this.semanticChunksLoaded = true;
        this.loadSemanticChunksForReader();
      }
    });
  }

  loadSemanticChunksForReader() {
    if (!this.bookId()) return;
    this.readerLoading.set(true);
    this.semanticChunks.set([]);
    this.selectedSemanticChunk.set(null);
    this.chunkTexts.set([]);
    
    this.api.getSemanticChunks(this.bookId(), this.selectedReaderMethod as 'embed'|'ner').subscribe({
      next: (chunks) => {
        this.semanticChunks.set(chunks);
        this.readerLoading.set(false);
      },
      error: () => {
        this.semanticChunks.set([]);
        this.readerLoading.set(false);
      }
    });
  }

  selectSemanticChunk(ch: any) {
    this.selectedSemanticChunk.set(ch);
    this.chunkTexts.set([{
      text: ch.text,
      entities: ch.entities || [],
      char_start: ch.char_start || 0
    }]);
  }

  /** Seleziona un intero capitolo semantico (tutti i suoi chunk concatenati) */
  selectSemanticSection(group: { sectionNum: number; label: string; parts: any[] }) {
    this.selectedSectionNum.set(group.sectionNum);
    this.selectedSemanticChunk.set(group.parts[0]);
    this.chunkTexts.set(group.parts.map(c => ({
      text: c.text,
      entities: c.entities || [],
      char_start: c.char_start || 0
    })));
  }

  toggleSection(secNum: number) {
    if (this.expandedSections.has(secNum)) {
      this.expandedSections.delete(secNum);
    } else {
      this.expandedSections.add(secNum);
    }
  }

  isSectionExpanded(secNum: number) {
    return this.expandedSections.has(secNum);
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
    const done = () => { if (++loaded === 3) this.loading.set(false); };

    this.api.getBookText(bookId).subscribe({ next: d => { this.textData.set(d); done(); }, error: done });
    this.api.getNer(bookId).subscribe({ next: d => { this.nerData.set(d); done(); }, error: () => { this.nerData.set(null); done(); } });
    this.api.getChapters(bookId).subscribe({ next: d => { this.chaptersData.set(d); done(); }, error: () => { this.chaptersData.set(null); done(); } });
    
    this.semanticChunksLoaded = false;
    if (this.view() === 'reader') {
      this.loadSemanticChunksForReader();
    }
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
