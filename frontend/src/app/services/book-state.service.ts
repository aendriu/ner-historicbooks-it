import { Injectable, signal, computed } from '@angular/core';
import { Book } from '../models/models';

@Injectable({ providedIn: 'root' })
export class BookStateService {
  readonly selectedBook = signal<Book | null>(null);
  readonly hasBook = computed(() => this.selectedBook() !== null);

  select(book: Book) { this.selectedBook.set(book); }
  clear()            { this.selectedBook.set(null); }
}
