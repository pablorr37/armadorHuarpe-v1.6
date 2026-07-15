from __future__ import annotations
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QMessageBox
)

from ui.widgets.textual_cards import TextualCard
from ui.widgets.textual_edit_dialog import TextualEditDialog


class TextualCardsView(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._limits = {
            "sin_foto": 220,
            "con_foto": 320,
            "epigrafe": 90,
        }
        self._candidates: list[dict] = []
        self._max_selected = 3

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.lbl = QLabel("Textuales detectados")
        self.btn_clear = QPushButton("Limpiar lista")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        top.addWidget(self.lbl)
        top.addStretch(1)
        top.addWidget(self.btn_clear)
        root.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.container = QWidget()
        self.lay = QVBoxLayout(self.container)
        self.lay.setContentsMargins(4, 4, 4, 4)
        self.lay.setSpacing(8)
        self.lay.addStretch(1)

        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

        self.btn_clear.clicked.connect(self.clear)

    def set_limits(self, sin_foto: int, con_foto: int, epigrafe: int):
        self._limits["sin_foto"] = int(sin_foto)
        self._limits["con_foto"] = int(con_foto)
        self._limits["epigrafe"] = int(epigrafe)
        self.refresh()

    def get_state(self) -> list[dict]:
        """Snapshot completo de los candidatos (para cachear por noticia al cambiar de
        pestaña de historia — ver EditorNotaWindow._snapshot_recursos)."""
        return [dict(c) for c in self._candidates]

    def set_state(self, candidates: list[dict]):
        """Restaura un snapshot de get_state(). NO emite `changed` — el llamador decide
        cuándo refrescar deducción/resaltado tras restaurar (evita recálculos duplicados)."""
        self._candidates = [dict(c) for c in candidates]
        self.refresh()

    def set_candidates(self, texts: list[str]):
        self._candidates = []
        for t in texts:
            self._candidates.append({
                "text": t,
                "removed": False,
                "selected": False,
                "con_foto": False,
                "orador_nombre": "",
                "orador_cargo": "",
                "foto": None,
            })
        self.refresh()

    def reanalizar_preservando(self, texts: list[str]):
        """Re-detecta candidatos PRESERVANDO los seleccionados actuales (con su
        nombre/cargo/foto): un Re-analizar no debe vaciar en silencio la selección
        que después se propaga al JSON del pegado. Emite `changed`."""
        previos = [dict(c) for c in self.selected_items()]
        self.set_candidates(texts)
        for prev in previos:
            hit = next((c for c in self._candidates
                        if not c["removed"] and c["text"] == prev["text"]), None)
            if hit is None:
                # El candidato ya no aparece en la detección: se conserva igual.
                self._candidates.append(dict(prev))
            else:
                hit.update({
                    "selected": True,
                    "con_foto": prev.get("con_foto", False),
                    "orador_nombre": prev.get("orador_nombre", ""),
                    "orador_cargo": prev.get("orador_cargo", ""),
                    "foto": prev.get("foto"),
                })
        self.refresh()
        self.changed.emit()

    def clear(self):
        self._candidates = []
        self.refresh()
        self.changed.emit()

    def selected_items(self) -> list[dict]:
        return [c for c in self._candidates if not c["removed"] and c["selected"]]

    def refresh(self):
        while self.lay.count() > 1:
            item = self.lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        total = sum(1 for c in self._candidates if not c["removed"])
        sel = sum(1 for c in self._candidates if not c["removed"] and c["selected"])
        self.lbl.setText(f"Textuales: {total} | Seleccionados: {sel}/{self._max_selected}")

        for idx, c in enumerate(self._candidates):
            if c["removed"]:
                continue

            limit = self._limits["con_foto"] if c["con_foto"] else self._limits["sin_foto"]
            cc = len(c["text"])
            counter = f"{cc}/{limit}"
            card = TextualCard(preview_text=c["text"], counter_text=counter)
            card.btn_foto.setChecked(c["con_foto"])
            card.set_selected(c["selected"])
            card.setProperty("over", cc > limit)
            card.style().unpolish(card)
            card.style().polish(card)

            def _remove(i=idx):
                self._candidates[i]["removed"] = True
                self.refresh()
                self.changed.emit()

            def _sel_changed(sel: bool, i=idx):
                if sel:
                    current = sum(1 for x in self._candidates if not x["removed"] and x["selected"])
                    if current >= self._max_selected:
                        QMessageBox.information(self, "Límite", f"Máximo {self._max_selected} textuales para este tipo.")
                        self._candidates[i]["selected"] = False
                        self.refresh()
                        return
                self._candidates[i]["selected"] = sel
                self.refresh()
                self.changed.emit()

            def _con_foto_changed(val: bool, i=idx):
                self._candidates[i]["con_foto"] = val
                if not val:
                    self._candidates[i]["foto"] = None
                self.refresh()
                self.changed.emit()

            def _edit(i=idx):
                self._candidates[i]["selected"] = True
                lim = self._limits["con_foto"] if self._candidates[i]["con_foto"] else self._limits["sin_foto"]
                foto = self._candidates[i]["foto"] or {}
                dlg = TextualEditDialog(
                    self,
                    texto=self._candidates[i]["text"],
                    nombre=self._candidates[i]["orador_nombre"],
                    cargo=self._candidates[i]["orador_cargo"],
                    con_foto=self._candidates[i]["con_foto"],
                    foto_path=foto.get("path", ""),
                    foto_epigrafe=foto.get("epigrafe", ""),
                    textual_limit=lim,
                    epigrafe_limit=self._limits["epigrafe"],
                )
                if dlg.exec_() == dlg.Accepted:
                    r = dlg.get_result()
                    self._candidates[i].update({
                        "text": r["texto"],
                        "orador_nombre": r["orador_nombre"],
                        "orador_cargo": r["orador_cargo"],
                        "con_foto": r["con_foto"],
                        "foto": r["foto"],
                    })
                    self.changed.emit()
                self.refresh()

            card.remove_requested.connect(_remove)
            card.selected_changed.connect(_sel_changed)
            card.con_foto_changed.connect(_con_foto_changed)
            card.edit_requested.connect(_edit)

            self.lay.insertWidget(self.lay.count() - 1, card)

    def add_preselected(self, texts: list[str]):
        """Add texts as pre-selected candidates (from blockquotes). Skips duplicates."""
        existing = {c["text"] for c in self._candidates}
        for t in texts:
            if not t or t in existing:
                continue
            self._candidates.append({
                "text": t,
                "removed": False,
                "selected": True,
                "con_foto": False,
                "orador_nombre": "",
                "orador_cargo": "",
                "foto": None,
            })
            existing.add(t)
        self.refresh()
        self.changed.emit()

    def set_tipo(self, tipo: str | None):
        tipo_counts = {
            "simple": 1, "x2": 2, "x3": 3,
            "con_foto": 1, "con_foto_xl": 1,
        }
        self._max_selected = tipo_counts.get(tipo or "", 4)
        self.refresh()

    def restore_saved(self, textual_data: dict):
        if not textual_data:
            return
        tipo = textual_data.get("tipo") or ""
        n_textos = {"simple": 1, "x2": 2, "x3": 3, "con_foto": 1, "con_foto_xl": 1}.get(tipo, 0)
        con_foto_tipo = tipo in ("con_foto", "con_foto_xl")
        foto_path = textual_data.get("foto") or None

        for i in range(1, n_textos + 1):
            texto = textual_data.get(f"texto{i}") or ""
            nombre = textual_data.get(f"nombre{i}") or ""
            cargo = textual_data.get(f"cargo{i}") or ""
            if not texto:
                continue
            found = False
            for c in self._candidates:
                if not c["removed"] and c["text"] == texto:
                    c["selected"] = True
                    c["orador_nombre"] = nombre
                    c["orador_cargo"] = cargo
                    if con_foto_tipo and i == 1 and foto_path:
                        c["con_foto"] = True
                        c["foto"] = {"path": foto_path, "epigrafe": ""}
                    found = True
                    break
            if not found:
                self._candidates.append({
                    "text": texto,
                    "removed": False,
                    "selected": True,
                    "con_foto": con_foto_tipo and i == 1 and bool(foto_path),
                    "orador_nombre": nombre,
                    "orador_cargo": cargo,
                    "foto": {"path": foto_path, "epigrafe": ""} if (con_foto_tipo and i == 1 and foto_path) else None,
                })
        self.refresh()
        # Notificar la restauración: dispara highlight/deducción/alerta en el editor
        # (antes el silencio dejaba los textuales cargados pero sin resaltar).
        self.changed.emit()
