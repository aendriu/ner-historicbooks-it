import { Component, OnInit, signal, effect, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../../services/api.service';
import { Book } from '../../models/models';
import { BookStateService } from '../../services/book-state.service';
import { Subscription, timer } from 'rxjs';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  styleUrl: './dashboard.component.scss',
  template: `
  <div class="layout-wrapper">

    <aside class="wireframe-sidebar">

      <!-- Upload -->
      <label class="w-btn w-btn-primary">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-4 h-4"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/></svg>
        Aggiungi libro
        <input type="file" accept=".json,.txt" (change)="onUpload($event)" class="hidden">
      </label>

      <!-- Seleziona libro -->
      <div class="select-wrapper">
        <select class="custom-select" [ngModel]="state.selectedBook()?.id" (ngModelChange)="onSelectBook($event)">
          <option [ngValue]="undefined" disabled selected>Seleziona libro...</option>
          <option *ngFor="let b of books()" [ngValue]="b.id">{{b.title}}</option>
        </select>
      </div>

      <!-- Pipeline Group -->
      <div class="pipeline-group">
        <button class="w-btn w-btn-primary" [disabled]="running() || !state.hasBook()" (click)="runAll()">
          Pipeline completa
        </button>
        <button class="w-btn w-btn-primary" [disabled]="running() || !state.hasBook()" (click)="runPhase('clean')">
          Pulizia OCR
        </button>
        <button class="w-btn w-btn-primary" [disabled]="running() || !state.hasBook()" (click)="runPhase('ner')">
          NER
        </button>
        <button class="w-btn w-btn-primary" [disabled]="running() || !state.hasBook()" (click)="openChunkingModal()">
          Chunking semantico
        </button>
        <button class="w-btn w-btn-primary" [disabled]="running() || !state.hasBook()" (click)="openSummaryModal()">
          Riassunti
        </button>
      </div>

      <div class="flex-1"></div>

      <!-- Analizza -->
      <div class="pipeline-group" style="background: rgba(99,102,241,0.05); border-color: rgba(99,102,241,0.1);">
        <button class="w-btn w-btn-accent" [disabled]="!state.hasBook()" (click)="goToAnalysis()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-4 h-4"><circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/></svg>
          Analizza libro
        </button>
        <button class="w-btn w-btn-primary" [disabled]="!state.hasBook() || exporting()" (click)="downloadExport()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-4 h-4"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
          {{ exporting() ? 'Preparazione ZIP...' : 'Scarica ZIP' }}
        </button>
      </div>

      <div *ngIf="errorMsg()" class="error-banner">
        ⚠️ {{ errorMsg() }}
      </div>

      <div *ngIf="toast()" class="text-xs text-center mt-2 p-2 rounded" style="background: rgba(99,102,241,0.1); color: var(--accent);">
        {{toast()}}
      </div>
    </aside>

    <main class="wireframe-main">
      <header class="wireframe-header">
        <h1 class="text-xl font-bold text-center" style="color: var(--text-primary);">
          {{ state.selectedBook() ? state.selectedBook()!.title : 'Nessun libro selezionato' }}
        </h1>
        <p class="text-center text-xs mt-1" style="color: var(--text-muted)">
          {{ state.selectedBook() ? state.selectedBook()!.author : '' }}
        </p>
      </header>

      <div class="wireframe-content relative">
        <div *ngIf="!state.hasBook()" class="absolute inset-0 flex items-center justify-center text-sm" style="color: var(--text-muted)">
          &lt;seleziona un libro per visualizzare il testo&gt;
        </div>
        <div *ngIf="state.hasBook() && loadingText()" class="absolute inset-0 flex items-center justify-center text-sm" style="color: var(--accent)">
          Caricamento testo in corso...
        </div>
        <div *ngIf="state.hasBook() && !loadingText() && textData()" class="h-full w-full">
          <p class="whitespace-pre-wrap text-[15px] leading-loose" style="color: var(--text-primary); font-family: 'Inter', sans-serif;">{{ textData().preview }}</p>
        </div>
        <div *ngIf="state.hasBook() && !loadingText() && !textData()" class="absolute inset-0 flex items-center justify-center text-sm text-red-500">
          Nessun testo pulito disponibile per questo libro.
        </div>
      </div>
    </main>

    <!-- Progress Modal -->
    <div *ngIf="showProgressModal()" class="modal-overlay">
      <div class="modal-content">
        <h2 class="text-xl font-bold" style="color: var(--text-primary);">Esecuzione {{progressPhase() | uppercase}} in corso...</h2>
        <div class="modal-logs" #logsContainer>
          <span *ngFor="let log of progressLogs()"> > {{log}}</span>
          <span *ngIf="progressStatus() === 'running'" class="animate-pulse">_</span>
        </div>
        <div class="flex justify-end gap-3 mt-2">
          <ng-container *ngIf="progressStatus() === 'running'">
            <button *ngIf="progressPhase() === 'summaries'"
                    class="w-btn" style="width:auto; background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.4); color:#ef4444;"
                    (click)="cancelSummarize()">
              ⛔ Stop
            </button>
            <button class="w-btn w-btn-primary" style="width: auto" disabled>
              Attendere...
            </button>
          </ng-container>
          <button *ngIf="progressStatus() !== 'running'" class="w-btn w-btn-accent" style="width: auto" (click)="closeProgressModal()">
            Chiudi
          </button>
        </div>
      </div>
    </div>

    <!-- VPN Wizard Modal -->
    <div *ngIf="showVpnWizard()" class="modal-overlay">
      <div class="modal-content" style="width: 450px;">
        <h2 class="text-xl font-bold" style="color: var(--text-primary);">Connessione VPN Aziendale</h2>
        <p class="text-sm mt-2" style="color: var(--text-muted); line-height: 1.5;">
          Vuoi connetterti al server aziendale remoto per accelerare l'intelligenza artificiale? 
          Richiede che la VPN (es. FortiClient) sia attiva.
        </p>
        
        <div class="mt-4" style="display: flex; flex-direction: column; gap: 0.5rem;">
          <label style="font-size: 0.85rem; color: var(--text-muted);">Indirizzo IP Ollama Remoto:</label>
          <input type="text" [(ngModel)]="remoteIp" class="w-input" [disabled]="testingVpn()" />
        </div>
        
        <div *ngIf="vpnError()" class="mt-3 text-xs p-2 rounded" style="background: rgba(239,68,68,0.1); color: #ef4444;">
          {{ vpnError() }}
        </div>

        <div class="flex justify-end gap-3 mt-6">
          <button class="w-btn" style="width: auto; background: transparent; border: 1px solid var(--border); color: var(--text-primary);" (click)="useLocal()" [disabled]="testingVpn()">
            No, usa PC locale
          </button>
          <button class="w-btn w-btn-accent" style="width: auto" (click)="checkRemote()" [disabled]="testingVpn()">
            {{ testingVpn() ? 'Test in corso...' : 'Sì, connettiti' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Chunking Method Modal -->
    <div *ngIf="showChunkingModal()" class="modal-overlay">
      <div class="modal-content" style="width: 480px;">
        <h2 class="text-xl font-bold" style="color: var(--text-primary);">🧩 Metodo di Chunking Semantico</h2>
        <p class="text-sm mt-2" style="color: var(--text-muted); line-height: 1.6;">
          Scegli come raggruppare il testo del libro in sezioni semantiche. I risultati dei due metodi verranno salvati separatamente e potranno essere confrontati nella sezione "Capitoli Semantici".
        </p>

        <div class="mt-5" style="display: flex; flex-direction: column; gap: 0.75rem;">
          <div (click)="selectedChunkMethod.set('embed')" style="padding:1rem; border-radius:10px; cursor:pointer; border: 2px solid; transition: all 0.15s;"
               [style.border-color]="selectedChunkMethod() === 'embed' ? 'var(--accent)' : 'var(--border)'"
               [style.background]="selectedChunkMethod() === 'embed' ? 'rgba(99,102,241,0.07)' : 'var(--bg-base)'">
            <div style="font-weight:700; color: var(--text-primary);">🔢 Basato su Embedding</div>
            <div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.25rem;">Calcola la similarità del coseno tra vettori semantici di paragrafi adiacenti. Un calo sotto il 50% indica un cambio di argomento.</div>
          </div>
          <div (click)="selectedChunkMethod.set('ner')" style="padding:1rem; border-radius:10px; cursor:pointer; border: 2px solid; transition: all 0.15s;"
               [style.border-color]="selectedChunkMethod() === 'ner' ? 'var(--accent)' : 'var(--border)'"
               [style.background]="selectedChunkMethod() === 'ner' ? 'rgba(99,102,241,0.07)' : 'var(--bg-base)'">
            <div style="font-weight:700; color: var(--text-primary);">🏷️ Basato su NER</div>
            <div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.25rem;">Confronta le entità nominate (persone, luoghi, ecc.) tra chunk adiacenti. Se la sovrapposizione è bassa, il testo appartiene a una sezione diversa.</div>
          </div>
        </div>

        <div class="flex justify-end gap-3 mt-6">
          <button class="w-btn" style="width:auto; background:transparent; border:1px solid var(--border); color:var(--text-primary);" (click)="showChunkingModal.set(false)">
            Annulla
          </button>
          <button class="w-btn w-btn-accent" style="width:auto" (click)="confirmChunking()">
            Avvia chunking
          </button>
        </div>
      </div>
    </div>

    <!-- Summary Method Modal -->
    <div *ngIf="showSummaryModal()" class="modal-overlay">
      <div class="modal-content" style="width: 480px;">
        <h2 class="text-xl font-bold" style="color: var(--text-primary);">📝 Metodo di Riassunto</h2>
        <p class="text-sm mt-2" style="color: var(--text-muted); line-height: 1.6;">
          Scegli su quali capitoli semantici generare i riassunti. I riassunti verranno salvati separatamente per ogni metodo e potranno essere confrontati nella sezione Analisi.
        </p>

        <div class="mt-5" style="display: flex; flex-direction: column; gap: 0.75rem;">
          <div (click)="selectedSummaryMethod.set('embed')" style="padding:1rem; border-radius:10px; cursor:pointer; border: 2px solid; transition: all 0.15s;"
               [style.border-color]="selectedSummaryMethod() === 'embed' ? 'var(--accent)' : 'var(--border)'"
               [style.background]="selectedSummaryMethod() === 'embed' ? 'rgba(99,102,241,0.07)' : 'var(--bg-base)'">
            <div style="font-weight:700; color: var(--text-primary);">🔢 Capitoli da Embedding</div>
            <div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.25rem;">Usa i capitoli semantici generati dal chunking basato su embedding vettoriale.</div>
          </div>
          <div (click)="selectedSummaryMethod.set('ner')" style="padding:1rem; border-radius:10px; cursor:pointer; border: 2px solid; transition: all 0.15s;"
               [style.border-color]="selectedSummaryMethod() === 'ner' ? 'var(--accent)' : 'var(--border)'"
               [style.background]="selectedSummaryMethod() === 'ner' ? 'rgba(99,102,241,0.07)' : 'var(--bg-base)'">
            <div style="font-weight:700; color: var(--text-primary);">🏷️ Capitoli da NER</div>
            <div style="font-size:0.78rem; color:var(--text-muted); margin-top:0.25rem;">Usa i capitoli semantici generati dal chunking basato sulle entità nominate (NER).</div>
          </div>
        </div>

        <div class="flex justify-end gap-3 mt-6">
          <button class="w-btn" style="width:auto; background:transparent; border:1px solid var(--border); color:var(--text-primary);" (click)="showSummaryModal.set(false)">
            Annulla
          </button>
          <button class="w-btn w-btn-accent" style="width:auto" (click)="confirmSummary()">
            Avvia riassunti
          </button>
        </div>
      </div>
    </div>

    <!-- Missing Models Modal -->
    <div *ngIf="showMissingModelsModal()" class="modal-overlay">
      <div class="modal-content" style="width: 500px;">
        <h2 class="text-xl font-bold" style="color: #ef4444;">⚠️ Modelli AI Mancanti</h2>
        <p class="text-sm mt-2" style="color: var(--text-muted); line-height: 1.6;">
          Il server Ollama è raggiungibile, ma <strong>non ha installato i modelli richiesti</strong>.
          Le fasi di Chunking Semantico e Riassunto AI falliranno se non intervieni.
        </p>

        <div class="mt-4" style="background: rgba(239,68,68,0.05); border: 1px solid rgba(239,68,68,0.2); border-radius: 8px; padding: 1rem;">
          <h3 class="text-sm font-bold" style="color: #ef4444; margin-bottom: 0.5rem;">Modelli mancanti:</h3>
          <ul class="text-sm" style="color: var(--text-primary); list-style-type: disc; padding-left: 1.5rem; margin-bottom: 1rem;">
            <li *ngFor="let m of missingModels()">{{ m }}</li>
          </ul>

          <h3 class="text-sm font-bold" style="color: var(--text-primary); margin-bottom: 0.5rem;">Modelli trovati sul server:</h3>
          <div class="text-xs" style="color: var(--text-muted); font-family: monospace; word-wrap: break-word;">
            {{ installedModels().length > 0 ? installedModels().join(', ') : 'Nessun modello installato.' }}
          </div>
        </div>

        <div class="mt-4 text-xs" style="color: var(--text-muted);">
          Puoi risolvere il problema aprendo un terminale sul server ed eseguendo:<br>
          <code style="background: var(--bg-base); padding: 2px 4px; border-radius: 4px; display: inline-block; margin-top: 4px;">ollama pull qwen3.5:9b && ollama pull bge-m3</code>
        </div>

        <div class="flex justify-end mt-6">
          <button class="w-btn" style="width:auto; background: #ef4444; color: white; border: none;" (click)="showMissingModelsModal.set(false)">
            Ho capito
          </button>
        </div>
      </div>
    </div>

  </div>
  `
})
export class DashboardComponent implements OnInit, OnDestroy {
  books = signal<Book[]>([]);
  toast = signal<string | null>(null);
  errorMsg = signal<string | null>(null);
  running = signal(false);
  exporting = signal(false);

  textData = signal<any>(null);
  loadingText = signal(false);

  showProgressModal = signal(false);
  progressPhase = signal('');
  progressLogs = signal<string[]>([]);
  progressStatus = signal('idle');
  private progressPollSub?: Subscription;
  private pollSub?: Subscription;

  // VPN Wizard state
  showVpnWizard = signal(false);
  remoteIp = signal('172.24.172.59');
  testingVpn = signal(false);
  vpnError = signal<string | null>(null);

  // Chunking method modal
  showChunkingModal = signal(false);
  selectedChunkMethod = signal<'embed' | 'ner'>('embed');

  // Summary method modal
  showSummaryModal = signal(false);
  selectedSummaryMethod = signal<'embed' | 'ner'>('embed');

  // Missing Models state
  showMissingModelsModal = signal(false);
  missingModels = signal<string[]>([]);
  installedModels = signal<string[]>([]);

  constructor(
    public state: BookStateService,
    private api: ApiService,
    private router: Router
  ) {
    effect(() => {
      const book = this.state.selectedBook();
      if (book) {
        this.loadBookText(book.id);
      } else {
        this.textData.set(null);
      }
    });
  }

  ngOnInit() {
    if (!localStorage.getItem('vpn_checked')) {
      this.showVpnWizard.set(true);
    }
    this.refreshBooks();
  }

  useLocal() {
    this.testingVpn.set(true);
    this.api.setOllamaSettings('localhost', '11434').subscribe({
      next: (res) => {
        localStorage.setItem('vpn_checked', 'local');
        this.showVpnWizard.set(false);
        this.testingVpn.set(false);
        this.showToast('Impostato server Ollama locale.');
        
        if (res.missing_models && res.missing_models.length > 0) {
          this.missingModels.set(res.missing_models);
          this.installedModels.set(res.installed_models || []);
          this.showMissingModelsModal.set(true);
        }
      },
      error: () => {
        localStorage.setItem('vpn_checked', 'local');
        this.showVpnWizard.set(false);
        this.testingVpn.set(false);
      }
    });
  }

  checkRemote() {
    this.testingVpn.set(true);
    this.vpnError.set(null);
    this.api.setOllamaSettings(this.remoteIp(), '11434').subscribe({
      next: (res) => {
        if (res.status === 'ok') {
          localStorage.setItem('vpn_checked', 'remote');
          this.showVpnWizard.set(false);
          this.showToast('Connesso al server aziendale!');
          
          if (res.missing_models && res.missing_models.length > 0) {
            this.missingModels.set(res.missing_models);
            this.installedModels.set(res.installed_models || []);
            this.showMissingModelsModal.set(true);
          }
        } else {
          this.vpnError.set(res.message || 'Errore sconosciuto. Passaggio a locale...');
          setTimeout(() => this.useLocal(), 2000);
        }
        this.testingVpn.set(false);
      },
      error: (err) => {
        this.vpnError.set('Impossibile raggiungere il server. Passaggio a locale in corso...');
        setTimeout(() => this.useLocal(), 2000);
      }
    });
  }

  ngOnDestroy() {
    if (this.pollSub) this.pollSub.unsubscribe();
    if (this.progressPollSub) this.progressPollSub.unsubscribe();
  }

  refreshBooks() {
    this.api.getBooks().subscribe(data => {
      this.books.set(data);
      const sel = this.state.selectedBook();
      if (sel) {
        const updated = data.find(b => b.id === sel.id);
        if (updated) this.state.selectedBook.set(updated);
      }
    });
  }

  onUpload(event: any) {
    const file = event.target.files[0];
    if (!file) return;
    this.api.uploadBook(file).subscribe({
      next: (res) => {
        this.showToast('Libro caricato con successo!');
        this.refreshBooks();
        setTimeout(() => this.onSelectBook(res.book_id), 500);
      },
      error: () => this.showToast('Errore durante l\'upload')
    });
  }

  onSelectBook(id: number) {
    const b = this.books().find(x => x.id === id);
    if (b) {
      this.state.selectedBook.set(b);
    }
  }

  loadBookText(id: number) {
    this.loadingText.set(true);
    this.api.getBookText(id).subscribe({
      next: (data) => {
        this.textData.set(data);
        this.loadingText.set(false);
      },
      error: () => {
        this.textData.set(null);
        this.loadingText.set(false);
      }
    });
  }

  runAll() {
    const book = this.state.selectedBook();
    if (!book) return;
    this.api.runAll(book.id).subscribe({
      next: () => {
        this.showToast('Pipeline avviata!');
        this.refreshBooks();
      },
      error: () => this.showToast('Errore avvio pipeline')
    });
  }

  runPhase(phase: string) {
    const book = this.state.selectedBook();
    if (!book) return;

    // Prerequisite checks — show inline error instead of alert()
    if (phase === 'ner' && !book.has_clean) {
      this.showError('Esegui prima la Pulizia OCR!');
      return;
    }
    if (phase === 'chunking' && !book.has_ner) {
      this.showError('Esegui prima l\'estrazione NER!');
      return;
    }
    if (phase === 'summaries' && !book.has_chunks) {
      this.showError('Esegui prima il Chunking Semantico!');
      return;
    }

    this.showProgressModal.set(true);
    this.progressPhase.set(phase);
    this.progressLogs.set([]);
    this.progressStatus.set('running');
    this.running.set(true);

    const finish = () => {
      this.running.set(false);
      this.refreshBooks();
    };

    const callApi = () => {
      switch (phase) {
        case 'clean': return this.api.runClean(book.id);
        case 'ner': return this.api.runNer(book.id);
        case 'chunking': return this.api.runChunking(book.id, this.selectedChunkMethod());
        case 'summaries': return this.api.runSummarize(book.id, this.selectedSummaryMethod());
        default: return this.api.runAll(book.id);
      }
    };

    callApi().subscribe({
      next: () => {
        // Il backend usa chiave diversa per i riassunti: '{id}_summarize_{method}'
        const progressKey = phase === 'summaries' ? `summarize_${this.selectedSummaryMethod()}` : phase;
        this.startProgressPolling(book.id, progressKey, finish);
      },
      error: (e) => {
        this.progressStatus.set('error');
        this.progressLogs.update(l => [...l, 'Errore API: ' + e.message]);
        finish();
      }
    });
  }

  openChunkingModal() {
    const book = this.state.selectedBook();
    if (!book) return;
    if (!book.has_ner) {
      this.showError('Esegui prima l\'estrazione NER!');
      return;
    }
    this.showChunkingModal.set(true);
  }

  confirmChunking() {
    this.showChunkingModal.set(false);
    this.runPhase('chunking');
  }

  openSummaryModal() {
    const book = this.state.selectedBook();
    if (!book) return;
    if (!book.has_chunks) {
      this.showError('Esegui prima il Chunking Semantico!');
      return;
    }
    this.showSummaryModal.set(true);
  }

  confirmSummary() {
    this.showSummaryModal.set(false);
    this.runPhase('summaries');
  }

  startProgressPolling(bookId: number, phase: string, onComplete: () => void) {
    if (this.progressPollSub) this.progressPollSub.unsubscribe();

    this.progressPollSub = timer(0, 1000).subscribe(() => {
      this.api.getProgress(bookId, phase).subscribe(res => {
        if (res.logs && res.logs.length > this.progressLogs().length) {
          this.progressLogs.set(res.logs);
        }
        
        if (res.status === 'completed' || res.status === 'error') {
          this.progressStatus.set(res.status);
          if (this.progressPollSub) this.progressPollSub.unsubscribe();
          onComplete();
        }
      });
    });
  }

  closeProgressModal() {
    this.showProgressModal.set(false);
  }

  cancelSummarize() {
    this.api.cancelSummarize().subscribe({
      next: () => {
        this.progressLogs.update(logs => [...logs, '⛔ Stop richiesto — il processo si fermerà dopo la sezione corrente...']);
      },
      error: () => {
        this.progressLogs.update(logs => [...logs, '⚠️ Impossibile inviare il segnale di stop.']);
      }
    });
  }

  downloadExport() {
    const book = this.state.selectedBook();
    if (!book) return;
    this.exporting.set(true);
    this.api.exportBook(book.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${book.title}_export.zip`;
        a.click();
        URL.revokeObjectURL(url);
        this.exporting.set(false);
      },
      error: () => {
        this.exporting.set(false);
        this.showError('Errore durante la generazione dello ZIP.');
      }
    });
  }

  goToAnalysis() {
    const book = this.state.selectedBook();
    if (book) {
      this.router.navigate(['/analysis', book.id]);
    }
  }

  showToast(msg: string) {
    this.toast.set(msg);
    setTimeout(() => this.toast.set(null), 3000);
  }

  /** Show a temporary error message in the template instead of alert() */
  showError(msg: string) {
    this.errorMsg.set(msg);
    setTimeout(() => this.errorMsg.set(null), 4000);
  }
}
