import { Component, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { BookTextData } from '../../../models/models';

@Component({
  selector: 'app-ocr-view',
  standalone: true,
  imports: [CommonModule],
  template: `
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
            <div class="value blue">{{ textData()!.raw_char_count | number }}</div>
          </div>
          <div class="stat-card">
            <div class="label">Caratteri dopo pulizia</div>
            <div class="value green">{{ textData()!.char_count | number }}</div>
          </div>
          <div class="stat-card">
            <div class="label">Caratteri rimossi</div>
            <div class="value red">{{ (textData()!.raw_char_count - textData()!.char_count) | number }}</div>
          </div>
          <div class="stat-card">
            <div class="label">% Pulizia</div>
            <div class="value purple">
              {{ ((textData()!.raw_char_count - textData()!.char_count) / textData()!.raw_char_count * 100 | number:'1.1-1') }}%
            </div>
          </div>
        </div>

        <!-- Side-by-side diff -->
        <div class="diff-grid">
          <div class="diff-panel">
            <div class="diff-panel-header dirty">❌ Testo Grezzo (OCR raw)</div>
            <pre>{{ textData()!.raw_preview }}</pre>
          </div>
          <div class="diff-panel">
            <div class="diff-panel-header clean">✅ Testo Pulito</div>
            <pre>{{ textData()!.preview }}</pre>
          </div>
        </div>
      </ng-container>
    </div>
  `
})
export class OcrViewComponent {
  textData = input<BookTextData | null>(null);
  loading = input<boolean>(false);
}
