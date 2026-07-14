import { Component, input, signal, computed, effect, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NerResult, ENTITY_COLORS, ENTITY_CSS_CLASSES } from '../../../models/models';
import { Chart, registerables } from 'chart.js';

Chart.register(...registerables);

@Component({
  selector: 'app-ner-view',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
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
  `
})
export class NerViewComponent {
  @ViewChild('pieCanvas') pieCanvas?: ElementRef<HTMLCanvasElement>;
  private chartInstance: any;

  nerData = input<NerResult | null>(null);
  loading = input<boolean>(false);

  selectedLabel = signal<string | null>(null);
  searchQuery = '';

  constructor() {
    // Render chart when data is available
    effect(() => {
      const ner = this.nerData();
      if (ner?.entities?.length) {
        setTimeout(() => this.renderChart(), 100);
      }
    });
  }

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

  getEntClass(label: string): string {
    return ENTITY_CSS_CLASSES[label] ?? 'ent-default';
  }

  getEntColor(label: string): string {
    return ENTITY_COLORS[label] ?? '#94a3b8';
  }
}
