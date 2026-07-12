import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ApiConfigComponent } from './components/api-config/api-config';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, ApiConfigComponent],
  templateUrl: './app.html',
})
export class App {}
