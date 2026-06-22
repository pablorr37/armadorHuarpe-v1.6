from datetime import datetime, date
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import logging
_log = logging.getLogger(__name__)


class ManagerScraper1:
    URL_NOTAS_NO_PUBLICADAS = "https://manager.diariohuarpe.com/list/notas/1?query%5Bnactiva%5D=on&queryEmpty=false"

    def __init__(self, driver, queue):
        self.driver = driver
        self.queue = queue  # instancia de scrape_queue

    def run(self):
        """Carga solo las notas NO PUBLICADAS de hoy y las encola."""
        self.driver.get(self.URL_NOTAS_NO_PUBLICADAS)

        # Espera a que esté la tabla
        tbody = self.driver.find_element(By.CSS_SELECTOR, "#tabla_list tbody")
        rows = tbody.find_elements(By.CSS_SELECTOR, "tr.tabla_nota")

        hoy = date.today()
        links_agregados = []

        for row in rows:
            try:
                # 1. ID de la nota
                nota_id = row.get_attribute("data-id")

                # 2. Fecha
                td_fecha = row.find_element(By.CSS_SELECTOR, "td[data-key='fecha_c']")
                fecha_txt = td_fecha.text.strip()  # ej: 20/11/2025 14:57

                # Convertir fecha
                try:
                    fecha_obj = datetime.strptime(fecha_txt, "%d/%m/%Y %H:%M")
                except ValueError:
                    continue  # fecha mal formada → ignorar

                # Filtrar solo HOY
                if fecha_obj.date() != hoy:
                    continue

                # 3. Título
                td_titulo = row.find_element(By.CSS_SELECTOR, "td[data-key='tituloNota']")
                titulo = td_titulo.text.strip()

                # 4. Secciones
                td_sec = row.find_element(By.CSS_SELECTOR, "td[data-key='secciones']")
                secciones = td_sec.text.strip().split(",")

                # 5. Construir link de edición
                link = f"https://manager.diariohuarpe.com/edit/notas/{nota_id}"

                # 6. Agregar a la cola del scraper 2
                self.queue.enqueue({
                    "id": nota_id,
                    "fecha": fecha_txt,
                    "titulo": titulo,
                    "secciones": secciones,
                    "url": link
                })

                links_agregados.append(link)

            except Exception as e:
                _log.info("ERROR analizando fila:", e)

        return links_agregados
