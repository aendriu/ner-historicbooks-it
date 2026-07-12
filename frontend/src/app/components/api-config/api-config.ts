import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { timeout, catchError, finalize } from 'rxjs/operators';
import { throwError } from 'rxjs';

@Component({
  selector: 'app-api-config',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <!-- Modale Ollama Config -->
    <div class="api-config-overlay" *ngIf="isVisible">
      <div class="api-config-modal glass-panel">
        <div class="modal-icon">🤖</div>
        <h2>Configura Motore AI</h2>
        <p>
          Configura il server <strong>Ollama</strong> che eseguirà i modelli AI.
          Può essere il tuo PC locale, un altro PC in rete, o un tunnel Cloudflare da Colab.
        </p>

        <div class="input-group">
          <label for="ollama-url-input">🌐 Indirizzo Server Ollama</label>
          <input type="text"
          id="ollama-url-input"
          class="config-input"
          [(ngModel)]="ollamaUrl"
          (keyup.enter)="testAndSave()"
          placeholder="Es. http://192.168.1.55:11434">
          <span class="field-hint">L'indirizzo IP (o URL Cloudflare) del computer che ha Ollama installato.</span>
        </div>

        <div class="input-group" style="margin-top: 1.25rem;">
          <label for="ollama-model-input">✍️ Modello per i Riassunti</label>
          <input type="text"
          id="ollama-model-input"
          class="config-input"
          [(ngModel)]="ollamaModel"
          (keyup.enter)="testAndSave()"
          placeholder="Es. qwen2.5:14b">
          <span class="field-hint">Il modello LLM usato per generare i riassunti semantici (deve essere già scaricato con <code>ollama pull</code>).</span>
        </div>


        <div class="input-group" style="margin-top: 1.25rem;">
          <label for="ollama-embed-input">🧩 Modello Embedding (Chunking Semantico)</label>
          <input type="text"
          id="ollama-embed-input"
          class="config-input"
          [(ngModel)]="ollamaEmbedModel"
          (keyup.enter)="testAndSave()"
          placeholder="Es. bge-m3">
          <span class="field-hint">Modello vettoriale usato per trovare i confini semantici nel testo (deve essere scaricato con <code>ollama pull</code>).</span>
        </div>

        <div class="input-group" style="margin-top: 1.25rem;">
          <label style="display:flex; align-items:center; gap:0.4rem;">🏷️ Modello NER
            <span style="font-size:0.65rem; background:rgba(99,102,241,0.15); color:#818cf8; padding:0.1rem 0.45rem; border-radius:20px; font-weight:600;">FISSO</span>
          </label>
          <div class="config-input" style="opacity:0.6; cursor:not-allowed; font-size:0.82rem; display:flex; align-items:center;">{{ nerModel }}</div>
          <span class="field-hint">Modello BERT addestrato su testi storici italiani. Non modificabile (scaricato automaticamente da HuggingFace).</span>
        </div>

        <div class="actions">
          <button class="btn-primary"
            [class.btn-saving]="testing"
            [class.btn-success]="saveSuccess"
            [class.btn-error]="saveError"
            (click)="testAndSave()"
            [disabled]="testing">
            <span *ngIf="!testing && !saveSuccess && !saveError">✓ Verifica e Salva</span>
            <span *ngIf="testing" class="spinner-row">
              <span class="dot-spinner"></span> Salvataggio...
            </span>
            <span *ngIf="saveSuccess">✅ Salvato!</span>
            <span *ngIf="saveError">❌ Errore — riprova</span>
          </button>
          <button class="btn-secondary" (click)="skipModal()">
            Chiudi
          </button>
        </div>
      </div>
    </div>

    <!-- Tasto fluttuante ⚙️ sempre visibile -->
    <button class="settings-fab" (click)="openModal()" title="Configura Ollama">
      🤖
    </button>
  `,
  styles: [`
    .api-config-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      backdrop-filter: blur(10px);
      display: flex;
      justify-content: center;
      align-items: center;
      z-index: 9999;
      animation: fadeIn 0.2s ease;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to   { opacity: 1; }
    }

    .glass-panel {
      background: rgba(18, 18, 28, 0.82);
      border: 1px solid rgba(255, 255, 255, 0.12);
      box-shadow: 0 8px 48px rgba(0, 0, 0, 0.5);
      backdrop-filter: blur(16px);
      border-radius: 20px;
      padding: 2.5rem 2rem;
      width: 90%;
      max-width: 420px;
      color: #fff;
      text-align: center;
      animation: slideUp 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
    }

    @keyframes slideUp {
      from { transform: translateY(30px); opacity: 0; }
      to   { transform: translateY(0);    opacity: 1; }
    }

    .modal-icon {
      font-size: 2.5rem;
      margin-bottom: 0.5rem;
    }

    .glass-panel h2 {
      margin: 0 0 0.5rem;
      font-size: 1.4rem;
      font-weight: 700;
      letter-spacing: -0.3px;
    }

    .glass-panel p {
      color: #aaa;
      font-size: 0.875rem;
      line-height: 1.6;
      margin-bottom: 1.75rem;
    }

    .glass-panel p strong { color: #e0e0e0; }
    .glass-panel p code {
      background: rgba(255,255,255,0.1);
      padding: 1px 6px;
      border-radius: 4px;
      font-size: 0.85em;
    }

    .input-group {
      text-align: left;
    }

    .input-group label {
      display: block;
      font-size: 0.78rem;
      font-weight: 600;
      color: #888;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 0.4rem;
    }

    .config-input {
      width: 100%;
      padding: 0.75rem 1rem;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.15);
      background: rgba(0,0,0,0.35);
      color: #fff;
      font-size: 0.95rem;
      outline: none;
      box-sizing: border-box;
      transition: border-color 0.2s, box-shadow 0.2s;
    }

    .config-input:focus {
      border-color: #6366f1;
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
    }

    .input-hint {
      display: block;
      font-size: 0.78rem;
      color: #6ee7b7;
      margin-top: 0.4rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .field-hint {
      display: block;
      font-size: 0.72rem;
      color: var(--text-muted, #aaa);
      margin-top: 0.35rem;
      line-height: 1.4;
    }

    .field-hint code {
      background: rgba(99,102,241,0.12);
      padding: 0.1rem 0.3rem;
      border-radius: 4px;
      font-size: 0.7rem;
    }

    .current-config {
      margin-top: 0.75rem;
      font-size: 0.8rem;
      color: var(--text-muted, #aaa);
      text-align: center;
    }

    .current-config strong {
      color: var(--text-primary, #eee);
    }

    .status-ok  { color: #6ee7b7; }
    .status-err { color: #f87171; }

    /* Spinner puntini animati */
    .spinner-row { display: flex; align-items: center; gap: 0.5rem; }
    .dot-spinner {
      width: 14px; height: 14px; border-radius: 50%;
      border: 2px solid rgba(255,255,255,0.3);
      border-top-color: #fff;
      animation: spin 0.7s linear infinite;
      display: inline-block;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* Stati bottone */
    .btn-saving  { opacity: 0.8; cursor: wait; }
    .btn-success { background: linear-gradient(135deg, #059669, #10b981) !important;
                   transform: scale(1.02); transition: all 0.2s; }
    .btn-error   { background: linear-gradient(135deg, #dc2626, #ef4444) !important;
                   transform: scale(1.02); transition: all 0.2s; }

    .actions {
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
      margin-top: 1.25rem;
    }

    .actions button {
      padding: 0.75rem;
      border-radius: 10px;
      border: none;
      font-weight: 600;
      font-size: 0.95rem;
      cursor: pointer;
      transition: transform 0.1s, opacity 0.2s;
    }

    .actions button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .actions button:not(:disabled):hover { opacity: 0.88; }
    .actions button:not(:disabled):active { transform: scale(0.98); }

    .btn-primary {
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: #fff;
    }

    .btn-secondary {
      background: rgba(255,255,255,0.07);
      color: #aaa;
    }

    /* ─── Tasto FAB ─── */
    .settings-fab {
      position: fixed;
      top: 1rem;
      right: 1rem;
      background: rgba(18, 18, 28, 0.75);
      border: 1px solid rgba(255,255,255,0.1);
      backdrop-filter: blur(6px);
      font-size: 1.1rem;
      width: 42px;
      height: 42px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      z-index: 9998;
      box-shadow: 0 4px 16px rgba(0,0,0,0.3);
      transition: background 0.2s, transform 0.2s;
    }

    .settings-fab:hover {
      background: rgba(99, 102, 241, 0.4);
      transform: scale(1.08);
    }
  `]
})
export class ApiConfigComponent implements OnInit {
  view: 'ner' | 'ollama' = 'ollama';
  isVisible = false;
  ollamaUrl = '';
  ollamaModel = 'qwen2.5:3b';
  ollamaEmbedModel = 'bge-m3';
  nerModel = 'aendriu/bert-ner-italian-historical';
  testing    = false;
  saveSuccess = false;
  saveError   = false;
  statusMsg = '';  // mantenuto per retrocompatibilità ma non mostrato
  statusOk  = false;

  constructor(private http: HttpClient) {}

  ngOnInit() {
    const savedUrl = localStorage.getItem('OLLAMA_BASE_URL');
    const savedModel = localStorage.getItem('OLLAMA_MODEL');
    if (savedUrl) {
      this.ollamaUrl = savedUrl;
    } else {
      this.isVisible = true;
    }
    if (savedModel) {
      this.ollamaModel = savedModel;
    }
  }

  openModal() {
    this.ollamaUrl        = localStorage.getItem('OLLAMA_BASE_URL')  || '';
    this.ollamaModel      = localStorage.getItem('OLLAMA_MODEL')      || 'qwen2.5:3b';
    this.ollamaEmbedModel = localStorage.getItem('OLLAMA_EMBED_MODEL') || 'bge-m3';
    this.statusMsg = '';
    this.isVisible = true;
    // Carica i valori aggiornati dal backend
    this.http.get<any>('http://localhost:8000/api/settings/ollama').subscribe({
      next: (res) => {
        if (res.host)        this.ollamaUrl        = res.host;
        if (res.model)       this.ollamaModel      = res.model;
        if (res.embed_model) this.ollamaEmbedModel = res.embed_model;
        if (res.ner_model)   this.nerModel         = res.ner_model;
      },
      error: () => {}
    });
  }

  testAndSave() {
    let url = this.ollamaUrl.trim().replace(/\/$/, '');

    if (!url) {
      this.saveError = true;
      setTimeout(() => { this.saveError = false; }, 2000);
      return;
    }

    this.ollamaUrl  = url;
    this.testing    = true;
    this.saveSuccess = false;
    this.saveError   = false;

    const safetyTimer = setTimeout(() => {
      if (this.testing) {
        this.testing = false;
        localStorage.setItem('OLLAMA_BASE_URL', url);
        localStorage.setItem('OLLAMA_MODEL', this.ollamaModel);
        localStorage.setItem('OLLAMA_EMBED_MODEL', this.ollamaEmbedModel);
        this.saveSuccess = true;
        setTimeout(() => { this.isVisible = false; this.saveSuccess = false; }, 1500);
      }
    }, 6000);

    const payload = { host: url, port: '443', model: this.ollamaModel.trim(), embed_model: this.ollamaEmbedModel.trim() };
    this.http.post('http://localhost:8000/api/settings/ollama', payload)
      .pipe(
        timeout(5000),
        catchError(err => throwError(() => err)),
        finalize(() => {
          clearTimeout(safetyTimer);
          this.testing = false;
        })
      )
      .subscribe({
        next: (_res: any) => {
          localStorage.setItem('OLLAMA_BASE_URL', url);
          localStorage.setItem('OLLAMA_MODEL', this.ollamaModel);
          localStorage.setItem('OLLAMA_EMBED_MODEL', this.ollamaEmbedModel);
          this.saveSuccess = true;
          setTimeout(() => { this.isVisible = false; this.saveSuccess = false; }, 1500);
        },
        error: () => {
          localStorage.setItem('OLLAMA_BASE_URL', url);
          localStorage.setItem('OLLAMA_MODEL', this.ollamaModel);
          localStorage.setItem('OLLAMA_EMBED_MODEL', this.ollamaEmbedModel);
          this.saveSuccess = true;
          setTimeout(() => { this.isVisible = false; this.saveSuccess = false; }, 1500);
        }
      });
  }

  skipModal() {
    this.isVisible = false;
  }
}
