# Guida all'uso di FortiVPN per il Deployment

## Cos'è un file `.ovpn`?

Un file `.ovpn` è un file di configurazione **OpenVPN** utilizzato anche da client compatibili come FortiClient. Contiene:

- L'indirizzo del server VPN aziendale
- I protocolli di cifratura e autenticazione
- I certificati e le chiavi crittografiche
- Le regole di routing per il traffico di rete

È un file di testo che permette di stabilire un **tunnel cifrato** tra il tuo computer e la rete aziendale.

## Perché usarlo?

| Vantaggio | Descrizione |
|---|---|
| **Sicurezza** | Tutto il traffico tra te e il server aziendale è crittografato end-to-end. |
| **Accesso interno** | Ti permette di raggiungere risorse disponibili solo nella rete privata aziendale. |
| **Semplicità** | Una volta configurato, la connessione si avvia con un singolo comando. |

## Come ottenere il file `.ovpn`

1. **Contatta l'amministratore di rete** della tua azienda e chiedi il file di configurazione VPN.
2. In alternativa, se ti hanno fornito credenziali FortiClient (host, porta, username, password), puoi usarle direttamente con `openfortivpn`.

## Dove salvare il file

```bash
# Crea una cartella dedicata
mkdir -p ~/vpn

# Salva il file .ovpn ricevuto dall'admin
cp /percorso/del/file/azienda.ovpn ~/vpn/

# Imposta permessi restrittivi (solo tu puoi leggerlo)
chmod 600 ~/vpn/azienda.ovpn
```

## Installazione del client VPN

```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y openfortivpn

# Fedora/RHEL
sudo dnf install openfortivpn

# Arch Linux
sudo pacman -S openfortivpn
```

## Connessione alla VPN

### Opzione 1: Con file `.ovpn`
```bash
sudo openfortivpn -c ~/vpn/azienda.ovpn
```

### Opzione 2: Con credenziali dirette
```bash
sudo openfortivpn <HOST_VPN>:<PORTA> \
  --username=<TUO_USERNAME> \
  --password=<TUA_PASSWORD>
```

### Opzione 3: Con file di configurazione personalizzato
Crea un file `~/vpn/config` con:
```
host = vpn.azienda.it
port = 443
username = tuo.username
password = tua.password
trusted-cert = <hash_certificato>
```
Poi connettiti con:
```bash
sudo openfortivpn -c ~/vpn/config
```

## Verifica della connessione

```bash
# Verifica che la VPN sia attiva
ip addr show ppp0

# Ping al server interno
ping <IP_SERVER_INTERNO>
```

## Deployment dell'applicazione

Una volta connesso alla VPN:

```bash
# 1. Connettiti al server via SSH
ssh utente@<IP_SERVER_INTERNO>

# 2. Clona o copia il progetto sul server
git clone <repo_url> ~/tirocinio
# oppure
scp -r ./tirocinio utente@<IP_SERVER>:~/

# 3. Avvia l'applicazione
cd ~/tirocinio
docker compose up -d --build

# 4. Attendi il download del modello (~2-5 minuti la prima volta)
docker logs -f tirocinio-ollama

# 5. Accedi all'applicazione dal browser
# http://<IP_SERVER_INTERNO>
```

## Variabili d'ambiente

Crea un file `.env` nella radice del progetto (non versionarlo!):

```dotenv
OLLAMA_HOST=ollama
OLLAMA_PORT=11434
OLLAMA_MODEL=qwen2.5:3b
DB_FILENAME=historicbooks.db
```

Docker Compose caricherà automaticamente queste variabili.

## Troubleshooting

| Problema | Soluzione |
|---|---|
| `Connection refused` | Verifica che la VPN sia attiva con `ip addr show ppp0` |
| `Permission denied` | Esegui `openfortivpn` con `sudo` |
| `Certificate error` | Aggiungi `--trusted-cert <hash>` al comando |
| `Timeout` | Verifica host e porta con il tuo admin di rete |
