import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { timeout, catchError, finalize } from 'rxjs/operators';
import { throwError } from 'rxjs';

const API_BASE = 'http://localhost:8000/api';

@Component({
  selector: 'app-api-config',
  standalone: true,
  imports: [CommonModule, FormsModule],
  styleUrl: './api-config.component.scss',
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
          <label for="ollama-model-input">✍️ Modello per i Riassunti dei Capitoli</label>
          <input type="text"
          id="ollama-model-input"
          class="config-input"
          [(ngModel)]="ollamaModel"
          (keyup.enter)="testAndSave()"
          placeholder="Es. qwen2.5:7b">
          <span class="field-hint">Modello usato per riassumere ogni singolo capitolo semantico (deve essere già scaricato con <code>ollama pull</code>).</span>
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
  `
})
export class ApiConfigComponent implements OnInit {
  isVisible = false;
  ollamaUrl         = 'http://host.docker.internal:11434';
  ollamaModel       = 'qwen2.5:3b';

  ollamaEmbedModel  = 'bge-m3';
  nerModel = 'aendriu/bert-ner-italian-historical';
  testing    = false;
  saveSuccess = false;
  saveError   = false;

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
    this.ollamaUrl         = localStorage.getItem('OLLAMA_BASE_URL')       || 'http://host.docker.internal:11434';
    this.ollamaModel       = localStorage.getItem('OLLAMA_MODEL')           || 'qwen2.5:3b';

    this.ollamaEmbedModel  = localStorage.getItem('OLLAMA_EMBED_MODEL')    || 'bge-m3';
    this.isVisible = true;
    // Carica i valori aggiornati dal backend
    this.http.get<any>(`${API_BASE}/settings/ollama`).subscribe({
      next: (res) => {
        if (res.host)         this.ollamaUrl         = res.host;
        if (res.model)        this.ollamaModel       = res.model;

        if (res.embed_model)  this.ollamaEmbedModel  = res.embed_model;
        if (res.ner_model)    this.nerModel           = res.ner_model;
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

    const payload = {
      host: url,
      port: '443',
      model: this.ollamaModel.trim(),

      embed_model: this.ollamaEmbedModel.trim()
    };
    this.http.post(`${API_BASE}/settings/ollama`, payload)
      .pipe(
        timeout(5000),
        catchError(err => throwError(() => err)),
        finalize(() => {
          this.testing = false;
        })
      )
      .subscribe({
        next: () => {
          localStorage.setItem('OLLAMA_BASE_URL',    url);
          localStorage.setItem('OLLAMA_MODEL',       this.ollamaModel);

          localStorage.setItem('OLLAMA_EMBED_MODEL', this.ollamaEmbedModel);
          this.saveSuccess = true;
          setTimeout(() => { this.isVisible = false; this.saveSuccess = false; }, 1500);
        },
        error: () => {
          this.saveError = true;
          setTimeout(() => { this.saveError = false; }, 2000);
        }
      });
  }

  skipModal() {
    this.isVisible = false;
  }
}
