import { Component, input, output, signal, computed, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { SummariesResponse, SummarySection } from '../../../models/models';

@Component({
  selector: 'app-summaries-view',
  standalone: true,
  imports: [CommonModule, FormsModule],
  encapsulation: ViewEncapsulation.None,
  template: `
    <div class="page-header">
      <h2>📝 Riassunti Semantici</h2>
      <p>Riassunti narrativi generati da AI per ogni sezione semantica. La NER retention misura quante entità chiave sopravvivono nel riassunto.</p>
    </div>

    <!-- Selettore metodo di chunking (embed / NER) -->
    <div style="display:flex; align-items:center; gap:0.5rem; padding:0 1rem 0.5rem; flex-wrap:wrap; flex-shrink:0;">
      <span style="font-size:0.75rem; color:var(--text-muted); font-weight:600; text-transform:uppercase; letter-spacing:.05em;">
        🧩 Capitoli da:
      </span>
      <button
        (click)="embedAvailable() && onChunkMethodSwitch.emit('embed')"
        [style.background]="selectedChunkMethod() === 'embed' ? 'rgba(99,102,241,0.2)' : 'var(--bg-base)'"
        [style.border]="selectedChunkMethod() === 'embed' ? '1.5px solid #6366f1' : '1.5px solid var(--border)'"
        [style.color]="selectedChunkMethod() === 'embed' ? '#6366f1' : (embedAvailable() ? 'var(--text-muted)' : 'var(--text-muted)')"
        [style.opacity]="embedAvailable() ? '1' : '0.4'"
        [style.cursor]="embedAvailable() ? 'pointer' : 'not-allowed'"
        style="padding:0.3rem 0.75rem; border-radius:20px; font-size:0.78rem; font-weight:600; transition:all 0.15s;">
        🔢 Embedding {{ !embedAvailable() ? '(non disponibile)' : '' }}
      </button>
      <button
        (click)="nerAvailable() && onChunkMethodSwitch.emit('ner')"
        [style.background]="selectedChunkMethod() === 'ner' ? 'rgba(99,102,241,0.2)' : 'var(--bg-base)'"
        [style.border]="selectedChunkMethod() === 'ner' ? '1.5px solid #6366f1' : '1.5px solid var(--border)'"
        [style.color]="selectedChunkMethod() === 'ner' ? '#6366f1' : (nerAvailable() ? 'var(--text-muted)' : 'var(--text-muted)')"
        [style.opacity]="nerAvailable() ? '1' : '0.4'"
        [style.cursor]="nerAvailable() ? 'pointer' : 'not-allowed'"
        style="padding:0.3rem 0.75rem; border-radius:20px; font-size:0.78rem; font-weight:600; transition:all 0.15s;">
        🏷️ NER {{ !nerAvailable() ? '(non disponibile)' : '' }}
      </button>
    </div>

    <!-- Selettore LLM: mostra i chip solo se ci sono più modelli disponibili -->
    <div *ngIf="summariesData()?.available_models?.length! > 1"
         style="display:flex; align-items:center; gap:0.5rem; padding:0 1rem 0.5rem; flex-wrap:wrap; flex-shrink:0;">
      <span style="font-size:0.75rem; color:var(--text-muted); font-weight:600; text-transform:uppercase; letter-spacing:.05em;">
        🤖 Modello:
      </span>
      <button *ngFor="let m of summariesData()?.available_models"
              (click)="onModelSwitch.emit(m)"
              [style.background]="selectedSummaryModel() === m ? 'rgba(99,102,241,0.2)' : 'var(--bg-base)'"
              [style.border]="selectedSummaryModel() === m ? '1.5px solid #6366f1' : '1.5px solid var(--border)'"
              [style.color]="selectedSummaryModel() === m ? '#6366f1' : 'var(--text-muted)'"
              style="padding:0.3rem 0.75rem; border-radius:20px; font-size:0.78rem; font-weight:600;
                     cursor:pointer; transition:all 0.15s; font-family:monospace;">
        {{ m }}
      </button>
    </div>

    <!-- Sinossi globale: barra collassabile + modal fullscreen -->
    <div *ngIf="bookGlobalSummary()" style="margin: 0 1rem 0.75rem 1rem; flex-shrink: 0;">
      <!-- Barra compatta cliccabile -->
      <div (click)="globalSummaryExpanded.set(true)" class="synopsis-bar">
        <span style="color:#6366f1; font-weight:700; font-size:0.9rem;">📖 Sinossi Globale</span>
        <div style="display:flex; align-items:center; gap:0.75rem;">
          <span style="font-size:0.72rem; background:rgba(99,102,241,0.15); color:#818cf8;
                       padding:0.15rem 0.55rem; border-radius:20px; font-weight:600;">
            {{ bookGlobalSummary()!.length | number }} car
          </span>
          <span style="font-size:0.72rem; background:rgba(99,102,241,0.15); color:#818cf8;
                       padding:0.15rem 0.55rem; border-radius:20px; font-weight:600;">
            ~{{ (bookGlobalSummary()!.split(' ').length) | number }} parole
          </span>
          <span style="color:#6366f1; font-size:0.8rem; opacity:0.75;">Espandi ↗</span>
        </div>
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
          <div>
            <h3 style="color:#6366f1; margin:0 0 0.4rem; font-size:1.1rem;">📖 Sinossi Globale</h3>
            <div style="display:flex; gap:0.6rem; flex-wrap:wrap;">
              <span style="font-size:0.7rem; background:rgba(99,102,241,0.12); color:#818cf8;
                           padding:0.15rem 0.55rem; border-radius:20px;">
                {{ bookGlobalSummary()!.length | number }} caratteri
              </span>
              <span style="font-size:0.7rem; background:rgba(99,102,241,0.12); color:#818cf8;
                           padding:0.15rem 0.55rem; border-radius:20px;">
                ~{{ bookGlobalSummary()!.split(' ').length | number }} parole
              </span>

            </div>
          </div>
          <button (click)="globalSummaryExpanded.set(false)" class="modal-close-btn">✕</button>
        </div>
        <!-- Testo scrollabile -->
        <div style="overflow-y:auto; padding:1.5rem; flex:1;">
          <p style="font-size:0.95rem; line-height:1.8; color:var(--text-primary);
                    white-space:pre-wrap; margin:0;">{{ bookGlobalSummary() }}</p>
        </div>
        <!-- Footer con stats aggiuntive -->
        <div style="padding:0.85rem 1.5rem; border-top:1px solid var(--border); flex-shrink:0;
                    display:flex; gap:1.5rem; flex-wrap:wrap; font-size:0.75rem; color:var(--text-muted);">
          <span>📊 Sezioni sintetizzate: <strong style="color:var(--text-primary)">{{ summariesData()?.sections?.length ?? '—' }}</strong></span>
          <span>📝 Caratteri totali libro: <strong style="color:var(--text-primary)">{{ totalBookChars() | number }}</strong></span>

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
              ⚠️ Entità perse nel riassunto: {{ sec.ner_retention?.lost?.join(', ') }}
            </p>
          </div>

          <!-- Navigation -->
          <div style="display:flex;gap:1rem;margin-top:1rem;">
            <button (click)="prevSummarySection()" [disabled]="selectedSummarySectionIndex() === 0"
              style="padding:0.5rem 1rem;border-radius:8px;border:1px solid var(--border);background:var(--bg-surface);color:var(--text-primary);cursor:pointer;font-weight:600;">
              ← Precedente
            </button>
            <button (click)="nextSummarySection()" [disabled]="selectedSummarySectionIndex() >= (summariesData()?.sections?.length! - 1)"
              style="padding:0.5rem 1rem;border-radius:8px;border:1px solid var(--border);background:var(--bg-surface);color:var(--text-primary);cursor:pointer;font-weight:600;">
              Successivo →
            </button>
          </div>
        </ng-container>
      </div>
    </div>
  `
})
export class SummariesViewComponent {
  summariesData        = input<SummariesResponse | null>(null);
  bookGlobalSummary    = input<string | null>(null);
  selectedSummaryModel = input<string | null>(null);
  selectedChunkMethod  = input<'embed' | 'ner'>('embed');
  embedAvailable       = input<boolean>(false);
  nerAvailable         = input<boolean>(false);

  onModelSwitch       = output<string>();
  onChunkMethodSwitch = output<'embed' | 'ner'>();

  globalSummaryExpanded = signal(false);
  selectedSummarySection = signal<SummarySection | null>(null);
  summarySearch = '';

  totalBookChars = computed<number>(() => {
    const d = this.summariesData();
    if (!d?.sections) return 0;
    let total = 0;
    for (const s of d.sections) total += (s.total_chars || 0);
    return total;
  });

  filteredSummarySections = computed(() => {
    const sections: SummarySection[] = this.summariesData()?.sections || [];
    const q = this.summarySearch.toLowerCase().trim();
    if (!q) return sections;
    return sections.filter((s: SummarySection) =>
      (s.topic_hint || '').toLowerCase().includes(q)
    );
  });

  selectedSummarySectionIndex = computed(() => {
    const sel = this.selectedSummarySection();
    if (!sel) return -1;
    return (this.summariesData()?.sections || []).findIndex(
      (s: SummarySection) => s.section_idx === sel.section_idx
    );
  });

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
}
