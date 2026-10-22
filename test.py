from playwright.sync_api import sync_playwright
import re
import time
import os

# Funzione per rendere il nome del file compatibile con il sistema operativo
def sanitize_filename(filename):
    # Rimuove caratteri non validi: \ / : * ? " < > |
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Limita la lunghezza a 150 caratteri per evitare errori di file system
    return filename[:150].strip()

def scrape_and_download_atti():
    # Crea la cartella di download se non esiste
    download_path = "atti_scaricati"
    if not os.path.exists(download_path):
        os.makedirs(download_path)

    results = []
    
    with sync_playwright() as p:
        # Avviamo il browser (headless=False per vedere cosa succede)
        browser = p.chromium.launch(headless=True) 
        # Importante: abilitiamo gli scaricamenti
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        
        print("Navigazione verso il sito...")
        page.goto("https://cloud.urbi.it/urbi/progs/urp/ur1ME001.sto?DB_NAME=n1200704&w3cbt=S")

        try:
            # 1. Clicca su Avanti
            print("Attesa del tasto 'Avanti'...")
            button_avanti_selector = "button:has-text('Avanti')"
            page.wait_for_selector(button_avanti_selector, timeout=20000)
            page.click(button_avanti_selector)
            print("Bottone cliccato.")

            # 2. Attesa caricamento tabella
            time.sleep(3)
            page.wait_for_selector("#idTabella2", timeout=20000)
            
            # 3. Recupera le righe
            rows = page.query_selector_all("#idTabella2 tbody tr")
            print(f"Trovate {len(rows)} righe.")

            for i, row in enumerate(rows):
                cells = row.query_selector_all("td")
                if len(cells) < 3:
                    continue
                
                # Estrazione testo della cella centrale
                cell_content = cells[1].inner_text()
                lines = [line.strip() for line in cell_content.split('\n') if line.strip()]
                
                if len(lines) < 3:
                    continue

                # Estrazione dati base
                ente = ""
                tipologia = ""
                testo_atto = ""
                data_inizio = ""
                data_fine = ""
                safe_name = "N/A"

                if "Ente Mittente" in lines[0]:
                    ente = lines[0].replace("Ente Mittente", "").strip()
                if "Tipologia Atto" in lines[1]:
                    tipologia = lines[1].replace("Tipologia Atto", "").strip()
                
                testo_atto = lines[2]
                
                for line in lines:
                    if "in pubblicazione dal" in line:
                        dates = re.findall(r'(\d{2}-\d{2}-\d{4})', line)
                        if len(dates) >= 2:
                            data_inizio = dates[0]
                            data_fine = dates[1]
                        break

                # --- LOGICA DI DOWNLOAD ---
                try:
                    print(f"Elaborazione riga {i+1}: {testo_atto[:50]}...")
                    
                    button_download = row.query_selector("button")
                    
                    if button_download:
                        with page.expect_download() as download_info:
                            button_download.click()
                        
                        download = download_info.value
                        
                        # Generiamo il nome del file
                        safe_name = sanitize_filename(testo_atto)
                        if not safe_name.lower().endswith('.pdf'):
                            safe_name += ".pdf"
                        
                        full_path = os.path.join(download_path, safe_name)
                        
                        # Salviamo il file
                        download.save_as(full_path)
                        print(f"Salvato: {safe_name}")
                        
                        # Piccola pausa tra un download e l'altro
                        time.sleep(1)
                    else:
                        print(f"Pulsante non trovato nella riga {i+1}")
                        
                except Exception as download_err:
                    print(f"Errore durante il download della riga {i+1}: {download_err}")
                    # Continua comunque con la prossima riga se il download fallisce
                
                # Aggiungiamo i risultati alla lista
                results.append({
                    "Ente mittente": ente,
                    "Tipologia Atto": tipologia,
                    "Testo dell'atto": testo_atto,
                    "Data inizio": data_inizio,
                    "Data fine": data_fine,
                    "File salvato": safe_name
                })

        except Exception as e:
            print(f"Errore durante l'esecuzione: {e}")
            page.screenshot(path="error_debug.png")

        browser.close()
    
    return results

if __name__ == "__main__":
    data = scrape_and_download_atti()
    print("\n--- Riepilogo Processo ---")
    if not data:
        print("Nessun dato estratto.")
    else:
        for entry in data:
            # Stampiamo usando una formattazione sicura
            testo_tagliato = entry['Testo dell\'atto'][:50].replace('\n', ' ')
            nome_file = entry['File salvato']
            print(f"-> {testo_tagliato}... [File: {nome_file}]")
