import { Routes } from '@angular/router';
import { DashboardComponent } from './components/dashboard/dashboard.component';
import { AnalysisComponent } from './components/analysis/analysis.component';

export const routes: Routes = [
  { path: '', component: DashboardComponent },
  { path: 'analysis/:id', component: AnalysisComponent },
  { path: '**', redirectTo: '' }
];
