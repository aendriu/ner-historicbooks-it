import { Component, input, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChunkingReport } from '../../../models/models';

@Component({
  selector: 'app-compare-view',
  standalone: true,
  imports: [CommonModule],
  encapsulation: ViewEncapsulation.None,
  template: `
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
            <div class="value blue">{{ reportData()!.embed_total_chunks }}</div>
          </div>
          <div class="stat-card">
            <div class="label">Sezioni Embed</div>
            <div class="value blue">{{ reportData()!.embed_total_sections }}</div>
          </div>
          <div class="stat-card">
            <div class="label">Chunk totali NER</div>
            <div class="value purple">{{ reportData()!.ner_total_chunks }}</div>
          </div>
          <div class="stat-card">
            <div class="label">Sezioni NER</div>
            <div class="value purple">{{ reportData()!.ner_total_sections }}</div>
          </div>
          <div class="stat-card">
            <div class="label">Confini Embed confermati da NER</div>
            <div class="value" [class.green]="reportData()!.avg_jaccard_score !== null && reportData()!.avg_jaccard_score! >= 0.6" [class.red]="reportData()!.avg_jaccard_score !== null && reportData()!.avg_jaccard_score! < 0.4">
              {{ reportData()!.avg_jaccard_score !== null ? (reportData()!.avg_jaccard_score! * 100).toFixed(1) + '%' : 'N/D' }}
            </div>
            <div style="font-size:0.68rem;color:var(--text-muted);margin-top:.2rem">su {{ reportData()!.embed_total_sections }} confini Embed</div>
          </div>
        </div>

        <!-- ── Sezione 2: Profilo di Similarità Coseno ── -->
        <h3 style="font-size:0.9rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin:0 0 .75rem">2 · Profilo di coerenza testuale (TF-IDF cosine similarity)</h3>
        <div class="diff-grid" style="margin-bottom:2rem">
          <!-- Embed -->
          <div class="card" *ngIf="reportData()!.embed_similarity">
            <h3>🔢 Metodo Embed</h3>
            <div class="stat-grid" style="grid-template-columns:1fr 1fr 1fr;margin-bottom:.75rem">
              <div class="stat-card">
                <div class="label">Sim. intra-sezione</div>
                <div class="value green">{{ reportData()!.embed_similarity.avg_intra !== null ? reportData()!.embed_similarity.avg_intra!.toFixed(3) : '—' }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Sim. al confine</div>
                <div class="value red">{{ reportData()!.embed_similarity.avg_boundary !== null ? reportData()!.embed_similarity.avg_boundary!.toFixed(3) : '—' }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Sim. cross-sezione</div>
                <div class="value red">{{ reportData()!.embed_similarity.avg_cross !== null ? reportData()!.embed_similarity.avg_cross!.toFixed(3) : '—' }}</div>
              </div>
            </div>
            <p style="font-size:0.78rem;color:var(--text-muted);line-height:1.5;margin:0">
              Un buon metodo mostra: <strong style="color:#4ade80">intra alta</strong> · <strong style="color:#f87171">al confine bassa</strong> · <strong style="color:#f87171">cross bassissima</strong>.
              Il Δ = intra − confine misura la "nitidezza" del taglio.
              <br><strong>Δ Embed = {{ reportData()!.embed_similarity.avg_intra !== null && reportData()!.embed_similarity.avg_boundary !== null ? (reportData()!.embed_similarity.avg_intra! - reportData()!.embed_similarity.avg_boundary!).toFixed(3) : '—' }}</strong>
              <span style="opacity:0.6">· {{ reportData()!.embed_similarity.n_intra }} coppie intra · {{ reportData()!.embed_similarity.n_boundary }} al confine · {{ reportData()!.embed_similarity.n_cross }} cross</span>
            </p>
          </div>
          <!-- NER -->
          <div class="card" *ngIf="reportData()!.ner_similarity">
            <h3>🏷️ Metodo NER</h3>
            <div class="stat-grid" style="grid-template-columns:1fr 1fr 1fr;margin-bottom:.75rem">
              <div class="stat-card">
                <div class="label">Sim. intra-sezione</div>
                <div class="value green">{{ reportData()!.ner_similarity.avg_intra !== null ? reportData()!.ner_similarity.avg_intra!.toFixed(3) : '—' }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Sim. al confine</div>
                <div class="value red">{{ reportData()!.ner_similarity.avg_boundary !== null ? reportData()!.ner_similarity.avg_boundary!.toFixed(3) : '—' }}</div>
              </div>
              <div class="stat-card">
                <div class="label">Sim. cross-sezione</div>
                <div class="value red">{{ reportData()!.ner_similarity.avg_cross !== null ? reportData()!.ner_similarity.avg_cross!.toFixed(3) : '—' }}</div>
              </div>
            </div>
            <p style="font-size:0.78rem;color:var(--text-muted);line-height:1.5;margin:0">
              <strong>Δ NER = {{ reportData()!.ner_similarity.avg_intra !== null && reportData()!.ner_similarity.avg_boundary !== null ? (reportData()!.ner_similarity.avg_intra! - reportData()!.ner_similarity.avg_boundary!).toFixed(3) : '—' }}</strong>
              — Il metodo con Δ maggiore segmenta in modo più netto.
              <span style="opacity:0.6">· {{ reportData()!.ner_similarity.n_intra }} coppie intra · {{ reportData()!.ner_similarity.n_boundary }} al confine · {{ reportData()!.ner_similarity.n_cross }} cross</span>
            </p>
          </div>
        </div>

        <!-- ── Sezione 3: Tabella Boundary Agreement ── -->
        <h3 style="font-size:0.9rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin:0 0 .75rem">3 · Corrispondenza confini Embed ↔ NER (tolleranza ±{{ reportData()!.tolerance_chars }} car.)</h3>
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
              <tr *ngFor="let row of reportData()!.comparison"
                  [style.background]="row.is_match ? 'rgba(74,222,128,0.04)' : 'rgba(248,113,113,0.04)'">
                <td style="padding:.55rem .9rem;color:var(--text-muted)">{{ row.embed_chunk_id }}</td>
                <td style="padding:.55rem .9rem;color:var(--text-primary)">{{ row.embed_topic }}</td>
                <td style="padding:.55rem .9rem;text-align:right;color:var(--text-muted);font-variant-numeric:tabular-nums">{{ row.embed_char | number }}</td>
                <td style="padding:.55rem .9rem;color:var(--text-muted)">{{ row.best_ner_chunk_id }}</td>
                <td style="padding:.55rem .9rem;color:var(--text-primary)">{{ row.ner_topic }}</td>
                <td style="padding:.55rem .9rem;text-align:right;color:var(--text-muted);font-variant-numeric:tabular-nums">{{ row.ner_char | number }}</td>
                <td style="padding:.55rem .9rem;text-align:right;font-variant-numeric:tabular-nums" [style.color]="row.dist_chars > reportData()!.tolerance_chars ? '#f87171' : '#4ade80'">{{ row.dist_chars | number }}</td>
                <td style="padding:.55rem .9rem;text-align:center">{{ row.is_match ? '✅' : '❌' }}</td>
              </tr>
            </tbody>
          </table>
          <div *ngIf="!reportData()!.comparison.length" class="empty-state" style="padding:1rem">Esegui entrambi i metodi di chunking per visualizzare la tabella.</div>
        </div>

        <!-- ── Sezione 4: Esempi di coppie ── -->
        <h3 style="font-size:0.9rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin:0 0 .75rem">4 · Esempi di coppie (Metodo Embed)</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-bottom:2rem">
          <!-- Intra -->
          <div class="card">
            <h3 style="color:#4ade80">✅ Intra-sezione (alta similarità attesa)</h3>
            <div *ngFor="let e of reportData()!.embed_similarity.intra.slice(0,5)" style="margin-bottom:.6rem;padding:.5rem;background:var(--bg-base);border-radius:8px;font-size:0.78rem">
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
            <div *ngFor="let e of reportData()!.embed_similarity.boundary.slice(0,5)" style="margin-bottom:.6rem;padding:.5rem;background:var(--bg-base);border-radius:8px;font-size:0.78rem">
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
            <div *ngFor="let e of reportData()!.embed_similarity.cross.slice(0,5)" style="margin-bottom:.6rem;padding:.5rem;background:var(--bg-base);border-radius:8px;font-size:0.78rem">
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
  `
})
export class CompareViewComponent {
  reportData = input<ChunkingReport | null>(null);
  reportLoading = input<boolean>(false);
}
