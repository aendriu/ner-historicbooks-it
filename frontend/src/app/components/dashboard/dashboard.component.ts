import { Component, OnInit, signal, effect, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService, Book } from '../../services/api.service';
import { BookStateService } from '../../services/book-state.service';
import { Subscription, timer } from 'rxjs';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  styles: [`
    :host { display: block; height: 100vh; background: var(--bg-base); }

    .layout-wrapper {
      display: flex;
      flex-direction: row;
      width: 100vw;
      height: 100vh;
      overflow: hidden;
    }

    .wireframe-sidebar {
      width: 300px;
      flex-shrink: 0;
      background: var(--bg-surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      padding: 1.5rem;
      gap: 1.5rem;
      height: 100vh;
      overflow-y: auto;
    }

    .wireframe-main {
      flex: 1;
      display: flex;
      flex-direction: column;
      background: var(--bg-surface);
      height: 100vh;
      overflow: hidden;
    }

    .wireframe-header {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      padding: 1.5rem 2rem;
      flex-shrink: 0;
    }

    .wireframe-content {
      flex: 1;
      padding: 2rem;
      overflow-y: auto;
      background: var(--bg-base);
    }

    .w-btn {
      width: 100%;
      padding: 0.8rem 1rem;
      border-radius: 12px;
      font-weight: 600;
      font-size: 0.9rem;
      cursor: pointer;
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.4rem;
      border: 1px solid transparent;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      box-sizing: border-box;
    }

    .w-btn-primary {
      background: rgba(99,102,241,0.1);
      color: var(--accent);
      border-color: rgba(99,102,241,0.3);
      box-shadow: 0 4px 12px rgba(99,102,241,0.05);
    }
    .w-btn-primary:hover {
      background: rgba(99,102,241,0.15);
      transform: translateY(-1px);
    }

    .w-btn-accent {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      box-shadow: 0 4px 12px rgba(99,102,241,0.2);
    }
    .w-btn-accent:hover {
      background: #4f46e5;
      transform: translateY(-1px);
    }

    .pipeline-group {
      background: var(--bg-base);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }

    .custom-select {
      width: 100%;
      padding: 0.8rem 1rem;
      border-radius: 12px;
      background: var(--bg-base);
      color: var(--text-primary);
      border: 1px solid var(--border);
      outline: none;
      cursor: pointer;
      appearance: none;
    }
    .custom-select:focus {
      border-color: var(--accent);
    }
    .select-wrapper { position: relative; }
    .select-wrapper::after {
      content: '▼';
      font-size: 0.6rem;
      position: absolute;
      right: 1rem;
      top: 50%;
      transform: translateY(-50%);
      pointer-events: none;
      color: var(--text-muted);
    }
    .custom-select option {
      background: var(--bg-surface);
      color: var(--text-primary);
    }

    .modal-overlay {
      position: fixed; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.4); backdrop-filter: blur(4px);
      display: flex; align-items: center; justify-content: center;
      z-index: 1000;
    }
    .modal-content {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      box-shadow: 0 10px 30px rgba(0,0,0,0.1);
      border-radius: 16px;
      width: 600px; max-width: 90vw;
      padding: 2rem;
      display: flex; flex-direction: column; gap: 1.5rem;
    }
    .modal-logs {
      background: var(--bg-base);
      border: 1px solid var(--border);
      border-radius: 8px; padding: 1rem;
      height: 300px; overflow-y: auto;
      font-family: monospace; font-size: 0.85rem; color: var(--text-muted);
      display: flex; flex-direction: column; gap: 0.5rem;
    }
    .modal-logs span:last-child { color: var(--accent); font-weight: bold; }
  `],
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
        <button class="w-btn w-btn-primary" [disabled]="running() || !state.hasBook()" (click)="runPhase('summaries')">
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
          <button *ngIf="progressStatus() === 'running'" class="w-btn w-btn-primary" style="width: auto" disabled>
            Attendere...
          </button>
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
  </div>
  `
})
export class DashboardComponent implements OnInit, OnDestroy {
  books = signal<Book[]>([]);
  toast = signal<string | null>(null);
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
      next: () => {
        localStorage.setItem('vpn_checked', 'local');
        this.showVpnWizard.set(false);
        this.testingVpn.set(false);
        this.showToast('Impostato server Ollama locale.');
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

    // Prerequisite checks for better UX
    if (phase === 'ner' && !book.has_clean) {
      alert('⚠️ Errore: Esegui prima la Pulizia OCR!');
      return;
    }
    if (phase === 'chunking' && !book.has_ner) {
      alert('⚠️ Errore: Esegui prima l\'estrazione NER!');
      return;
    }
    if (phase === 'summaries' && !book.has_chunks) {
      alert('⚠️ Errore: Esegui prima il Chunking Semantico!');
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
        case 'summaries': return this.api.runSummarize(book.id, 'embed');
        default: return this.api.runAll(book.id);
      }
    };

    callApi().subscribe({
      next: () => {
        // Il backend usa chiave diversa per i riassunti: '{id}_summarize_embed'
        const progressKey = phase === 'summaries' ? 'summarize_embed' : phase;
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
      alert('⚠️ Errore: Esegui prima l\'estrazione NER!');
      return;
    }
    this.showChunkingModal.set(true);
  }

  confirmChunking() {
    this.showChunkingModal.set(false);
    this.runPhase('chunking');
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
        alert('Errore durante la generazione dello ZIP.');
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
}
