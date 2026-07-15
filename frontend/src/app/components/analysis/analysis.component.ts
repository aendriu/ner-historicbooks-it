import { Component, OnInit, signal, ViewChild, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../../services/api.service';
import {
  NerResult, Chapter, BookTextData,
  SummariesResponse, ChunkingReport, SummarySection
} from '../../models/models';
import { BookStateService } from '../../services/book-state.service';

import { OcrViewComponent } from './ocr-view/ocr-view.component';
import { NerViewComponent } from './ner-view/ner-view.component';
import { ReaderViewComponent } from './reader-view/reader-view.component';
import { SummariesViewComponent } from './summaries-view/summaries-view.component';
import { CompareViewComponent } from './compare-view/compare-view.component';

@Component({
  selector: 'app-analysis',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    OcrViewComponent, NerViewComponent, ReaderViewComponent,
    SummariesViewComponent, CompareViewComponent
  ],
  styleUrl: './analysis.component.scss',
  encapsulation: ViewEncapsulation.None,
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
      <app-ocr-view *ngIf="view() === 'ocr'"
        [textData]="textData()"
        [loading]="loading()">
      </app-ocr-view>

      <app-ner-view *ngIf="view() === 'ner'"
        [nerData]="nerData()"
        [loading]="loading()">
      </app-ner-view>

      <app-reader-view *ngIf="view() === 'reader'"
        [chaptersData]="chaptersData()"
        [bookId]="bookId()"
        [loading]="loading()"
        (onCompareClick)="view.set('compare'); loadReport()">
      </app-reader-view>

      <app-summaries-view *ngIf="view() === 'summaries'"
        [summariesData]="summariesData()"
        [bookGlobalSummary]="bookGlobalSummary()"
        [selectedSummaryModel]="selectedSummaryModel()"
        [selectedChunkMethod]="selectedSummaryChunkMethod()"
        [embedAvailable]="embedSummariesData() !== null"
        [nerAvailable]="nerSummariesData() !== null"
        (onModelSwitch)="switchSummaryModel($event)"
        (onChunkMethodSwitch)="switchSummaryChunkMethod($event)">
      </app-summaries-view>

      <app-compare-view *ngIf="view() === 'compare'"
        [reportData]="reportData()"
        [reportLoading]="reportLoading()">
      </app-compare-view>
    </main>
  </div>
  `
})
export class AnalysisComponent implements OnInit {
  view = signal<'ocr' | 'ner' | 'reader' | 'summaries' | 'compare'>('ocr');
  loading = signal(true);

  textData = signal<BookTextData | null>(null);
  nerData = signal<NerResult | null>(null);
  chaptersData = signal<Chapter[] | null>(null);
  bookGlobalSummary = signal<string | null>(null);

  summariesData = signal<SummariesResponse | null>(null);
  selectedSummaryModel = signal<string | null>(null);

  // Riassunti per entrambi i metodi di chunking, caricati in parallelo
  embedSummariesData = signal<SummariesResponse | null>(null);
  nerSummariesData   = signal<SummariesResponse | null>(null);
  // Metodo di chunking attualmente visualizzato nella tab riassunti
  selectedSummaryChunkMethod = signal<'embed' | 'ner'>('embed');

  bookId = signal<number>(0);

  // Report confronto metodi
  reportLoading = signal(false);
  reportData = signal<ChunkingReport | null>(null);

  @ViewChild(SummariesViewComponent) summariesView?: SummariesViewComponent;

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private api: ApiService,
    private state: BookStateService
  ) {}

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
    const done = () => { if (++loaded === 5) this.loading.set(false); };

    this.api.getBookText(bookId).subscribe({ next: d => { this.textData.set(d); done(); }, error: done });
    this.api.getNer(bookId).subscribe({ next: d => { this.nerData.set(d); done(); }, error: () => { this.nerData.set(null); done(); } });
    this.api.getChapters(bookId).subscribe({ next: d => { this.chaptersData.set(d); done(); }, error: () => { this.chaptersData.set(null); done(); } });

    // Carica riassunti embed
    this.api.getSummaries(bookId, 'embed').subscribe({
      next: d => {
        this.embedSummariesData.set(d);
        // embed è il metodo di default: attiva subito se è il selezionato
        if (this.selectedSummaryChunkMethod() === 'embed') {
          this._applySummaryData(d);
        }
        done();
      },
      error: () => {
        this.embedSummariesData.set(null);
        // se embed non c'è, prova NER come fallback
        if (this.selectedSummaryChunkMethod() === 'embed' && this.nerSummariesData()) {
          this._applySummaryData(this.nerSummariesData()!);
          this.selectedSummaryChunkMethod.set('ner');
        }
        done();
      }
    });

    // Carica riassunti NER in parallelo
    this.api.getSummaries(bookId, 'ner').subscribe({
      next: d => {
        this.nerSummariesData.set(d);
        // Attiva NER se embed non era disponibile e si era in embed
        if (this.embedSummariesData() === null) {
          this._applySummaryData(d);
          this.selectedSummaryChunkMethod.set('ner');
        }
        done();
      },
      error: () => { this.nerSummariesData.set(null); done(); }
    });
  }

  /** Promuove un SummariesResponse come dato correntemente visualizzato. */
  private _applySummaryData(d: SummariesResponse) {
    this.summariesData.set(d);
    this.bookGlobalSummary.set(d.global_summary || null);
    this.selectedSummaryModel.set(
      d.current_model_file?.replace('summaries_', '').replace('.json', '').replace(/_/g, '.') ?? null
    );
  }

  switchSummaryModel(model: string) {
    const bookId = this.bookId();
    const method = this.selectedSummaryChunkMethod();
    if (!bookId || this.selectedSummaryModel() === model) return;
    this.api.getSummaries(bookId, method, model).subscribe({
      next: d => {
        this._applySummaryData(d);
        this.selectedSummaryModel.set(model);
        // aggiorna la cache del metodo corrente
        if (method === 'embed') this.embedSummariesData.set(d);
        else this.nerSummariesData.set(d);
      }
    });
  }

  /** Cambia il metodo di chunking su cui visualizzare i riassunti (embed ↔ ner). */
  switchSummaryChunkMethod(method: 'embed' | 'ner') {
    if (this.selectedSummaryChunkMethod() === method) return;
    this.selectedSummaryChunkMethod.set(method);
    const cached = method === 'embed' ? this.embedSummariesData() : this.nerSummariesData();
    if (cached) {
      // già in cache: switch immediato, nessuna chiamata API
      this._applySummaryData(cached);
    } else {
      // non ancora caricato: fetch on demand
      this.api.getSummaries(this.bookId(), method).subscribe({
        next: d => {
          if (method === 'embed') this.embedSummariesData.set(d);
          else this.nerSummariesData.set(d);
          this._applySummaryData(d);
        },
        error: () => { this.summariesData.set(null); this.bookGlobalSummary.set(null); }
      });
    }
  }

  goBack() { this.router.navigate(['/']); }

  loadReport() {
    this.reportLoading.set(true);
    this.api.getChunkingReport(this.bookId()).subscribe({
      next: (data) => { this.reportData.set(data); this.reportLoading.set(false); },
      error: () => { this.reportData.set(null); this.reportLoading.set(false); }
    });
  }
}
