# preprocessing

Tool in C per fare preprocessing dei file JSON in `books/metadata/`.

Questo programma legge ogni file `*.json`, prende **solo** il campo stringa JSON `"contenuto"`, lo pulisce con una serie di regole (tokenizzazione + filtri + fix OCR), e riscrive un nuovo JSON di output mantenendo tutto il resto invariato.

L'obiettivo è avere un preprocessing **ripetibile** e **automatizzabile** anche su molti file, con una modalità interattiva (menu) e una modalità batch multithread.

## Aggiornamento Lambda (modalita atomica)

Il binario `preprocess_c` ora e pensato per esecuzione atomica (una richiesta -> un output) ed e adatto a AWS Lambda.

Modifiche principali:

- niente scansione cartelle interna;
- niente thread;
- niente menu interattivo.

Interfacce disponibili:

```bash
./preprocess_c --process-file <input_json> <output_json>
./preprocess_c --clean-text "testo da pulire"
cat input.txt | ./preprocess_c --clean-stdin
```

Per elaborare una cartella intera, fai il loop da shell esterna (come in `run_pipeline.sh`).

## Input / Output

- Input: `books/metadata/*.json` (campo JSON `"contenuto"`).
- Output: `preprocessing/output/<stesso_nome_file>.json`.

Nota: l'output è un JSON completo (non solo il testo pulito). Viene modificato esclusivamente il valore di `"contenuto"`.

## Build

Da repository root:

- `cd preprocessing`
- `make clean && make`

Esegue il binario: `./preprocess_c`.

Requisiti:

- Compiler C (es. `gcc` o `clang`)
- Linux (il programma ricava la repo root da `/proc/self/exe`)
- `pthread`
- cJSON (libreria di sistema)

Esempio (Debian/Ubuntu): `sudo apt install libcjson-dev`
Header atteso: `<cjson/cJSON.h>`.

## Come si usa (menu)

Lanciando `./preprocess_c` compare un menu con queste opzioni:

- **1. Pulisci un file**
	- Mostra la lista dei file in `books/metadata/` e permette di scegliere un indice.
	- Produce `preprocessing/output/<file>.json`.

- **2. Pulisci tutti i file**
	- Avvia il preprocessing su tutti i JSON in `books/metadata/`.
	- Modello: usa **al massimo 200 thread**; se i file sono più di 200, li processa a *batch* successivi.
	- Nota: questa opzione **non esegue automaticamente il confronto**.

- **3. Confronta un file**
	- Confronta il file di input con quello preprocessato in output.
	- Il confronto è “di supporto”: non è un diff testuale stile `difflib`.

- **4. Confronta tutti i file**
	- Scorre tutti i file in `books/metadata/` e confronta quelli che hanno già un corrispondente in `preprocessing/output/`.
	- Esecuzione sequenziale.

- **5. Stampa un file pulito**
	- Carica dall'output e stampa a schermo solo `"contenuto"`.

In varie opzioni viene stampato anche un **timer** (durata per operazione).

## Cosa avviene:

### 1) Gestione path (repo root)

Il programma costruisce i path in modo indipendente dalla working directory:

- ricava la repo root dalla posizione dell'eseguibile (`/proc/self/exe`)
- poi usa:
	- `books/metadata` come input
	- `preprocessing/output` come output

Questo evita problemi se lanci il binario da cartelle diverse.

### 2) JSON: parsing con cJSON

Ora viene usata la libreria **cJSON**:

1. parse completo del file JSON
2. lettura di `"contenuto"`
3. cleaning del testo
4. sostituzione del campo `"contenuto"`
5. serializzazione JSON finale

Nota: la serializzazione può modificare formattazione/ordine dei campi, ma i metadati restano invariati.

### 3) Confronto token

Per il confronto tra input/output viene usata una semplice mappa in memoria (array dinamico), senza dipendenze esterne.

### 3) Cleaning del testo (alto livello)

Il cleaning è una pipeline di euristiche pensata per testi letterari/ocrizzati.
In breve include:

- normalizzazioni e fix OCR comuni (es. apostrofi/lettere ambigue)
- tokenizzazione e ricostruzione
- rimozione di token considerati “spazzatura” (pattern improbabili, densità simboli alta, forme alfanumeriche sospette, ecc.)
- gestione di intestazioni/interruzioni tipiche (es. titoli/marker in maiuscolo)
- rimozione di “finestre” di garbage (sequenze lunghe di token invalidi)

Importante: sono regole **euristiche**. Se cambi dominio o input, alcune scelte potrebbero essere troppo aggressive.

### Token scartati (regole ESATTE)

Durante il cleaning, il testo viene spezzato in token per whitespace. Ogni token (o sotto-token, se una correzione produce più token) viene tenuto solo se passa tutte le regole di validazione sotto. In caso contrario viene scartato.

Di seguito le regole **esattamente come implementate** in `is_valid_token()`.

1) Struttura di base (`check_basic_structure`)

Un token è accettabile se vale almeno una di queste condizioni:

- contiene almeno una vocale (incluse vocali accentate supportate)
- oppure contiene almeno una cifra (`0-9`)
- oppure è un numero romano composto solo da lettere maiuscole tra `I,V,X,L,C,D,M`

Eccezioni che rendono valido il token anche senza vocale/cifra/romano:

- token che è solo un trattino tra `-`, `—`, `–`
- token che è esattamente uno dei prefissi con apostrofo iniziale: `'l`, `’l`, `'n`, `’n`, `'d`, `’d`
- token che **non** contiene vocali ma termina con apostrofo (`'` o `’`) e contiene almeno una lettera (caso di elisione)

2) Token di un solo carattere (`check_single_char`)

Se il token ha lunghezza 1, è accettato solo se:

- è un trattino (`-`, `—`, `–`), oppure
- è uno tra: `a e i o à è é ì ò ù 0..9` (case-insensitive), oppure
- è una singola lettera maiuscola (qualsiasi `A..Z` classificata come maiuscola)

3) Caratteri proibiti (`check_forbidden_chars`)

Se il token contiene **anche solo uno** dei seguenti caratteri, viene scartato:

`*  >  <  |  +  ^  =  £  $  %  €`

4) Densità di simboli (`check_symbol_density`)

Si ignora `«` e `»` nel calcolo. Sul resto:

- se la lunghezza “pulita” è 0 → scarto
- se la lunghezza “pulita” è > 1, allora la frazione

	(numero di caratteri alfanumerici / lunghezza pulita)

	deve essere ≥ 0.5, altrimenti scarto.

Per “alfanumerico” qui si intendono lettere/cifre + alcune vocali accentate gestite.

5) Casing (maiuscole/minuscole) (`check_casing`)

Accettato se il token è:

- tutto maiuscolo, oppure
- tutto minuscolo (incluse alcune accentate minuscole), oppure
- “TitleCase-like”: la prima lettera è maiuscola e le successive lettere sono minuscole

Altrimenti viene scartato se contiene una lettera maiuscola in posizione interna (indice > 0) **a meno che** quella maiuscola sia preceduta da:

- apostrofo (`'` o `’`), oppure
- trattino (`-`, `—`, `–`)

6) Finale “straniero” (`check_foreign_ending`)

Se l’ultimo carattere (case-insensitive) è uno tra `k w x y j`, il token viene scartato.

7) Uso della lettera “h” (`check_h_usage`)

- Se la prima lettera (dopo aver tolto punteggiatura iniziale) è maiuscola → token accettato.
- Altrimenti, se nel token compare `h`:
	- vengono ignorati i digrammi `ch`, `gh`, `ph` (l’`h` in questi casi non conta)
	- se dopo questa rimozione resta ancora una `h`, allora il token è accettato **solo** se, dopo aver rimosso punteggiatura e apostrofi ai bordi, è nella whitelist (interiezioni e forme verbali come `ho`, `ha`, `hanno`, `ahimè`, ecc.)

8) Doppie vocali specifiche (`check_double_vowels`)

Se in minuscolo contiene la sottostringa `aa` oppure `uu`, il token viene scartato.

9) Apostrofo iniziale (`check_starting_apostrophe`)

- Se è esattamente uno dei token ammessi (`'l`, `’l`, `'n`, `’n`, `'d`, `’d`) → accettato.
- Se inizia con `'` o `’` ma non è nella lista sopra, allora deve avere lunghezza > 2 (almeno 3 caratteri) altrimenti scarto.

10) Alfanumerico misto (`check_mixed_alphanumeric`)

Se contiene **sia** lettere **sia** cifre nello stesso token, viene scartato.

### Rimozione di “garbage sequences” (regola aggiuntiva)

Dopo aver validato i singoli token, viene applicata anche una rimozione per sequenze di token “troppo corti”:

- finestra scorrevole di 15 token
- per ogni finestra si calcola una lunghezza pesata per token
	- si rimuove punteggiatura `. , ; : ! ? ( ) [ ] { } « » - — – ' ’`
	- se il token (ripulito) è tutto maiuscolo (lunghezza > 1) oppure è un numero romano, allora vale almeno 5 (minimo)
- se la media di queste lunghezze pesate nella finestra è < 2.5, allora **tutti** i 15 token della finestra vengono marcati come “garbage” e rimossi.

## Limitazioni note

- **Threading**: il modello è volutamente semplice: fino a 200 thread in parallelo e poi batch successivi. Se serve scalare meglio (o controllare meglio il carico), conviene passare a un thread-pool.
- **JSON mirato**: robusto finché il formato dei file resta coerente; non è un parser generale.
- **Euristiche**: alcune regole possono rimuovere testo valido (false positive). Consigliato validare su un campione.

## Troubleshooting

- Se l'output non viene scritto, controlla permessi e che esista `preprocessing/output/`.
- Se un file non contiene `"contenuto"` oppure è malformato, verrà segnalato e saltato.
- Se vuoi verificare rapidamente che il tool funzioni:
	- `printf "1\n0\nq\n" | ./preprocess_c`


## Note

- Input: `books/metadata/*.json` (campo JSON `"contenuto"`).
- Output: `preprocessing/output/<stesso_nome_file>.json`.
- L'opzione `2` del menu avvia il preprocessing di **tutti** i file (multithread, fino a 200).
- L'opzione `1` permette di selezionare un singolo file (per indice) e preprocessarlo.
