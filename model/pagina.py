# model/pagina.py

from dataclasses import dataclass

@dataclass
class Pagina:
    numero: int
    asignado: bool = False
    armado: bool = False
    fotocromia: bool = False
    corregido: bool = False
    apdf: bool = False
    revisado: bool = False
    impreso: bool = False
    
    asignada_por_ini: bool = False
    aviso_full: bool = False
    aviso_half: bool = False
    aviso_footer: bool = False
    aviso_robapagina: bool = False
    aviso_nombre: str = ""
    tapa_foto: bool = False
    tapa_titulo: bool = False
    listo_para_armar: bool = False
    armado_bot: bool = False
    editando: bool = False
    editando_por: str = ""
    editando_por_otro: bool = False
    mono_extra: str = ""
    seccion: str = ""
    estado: str = ""

    def estado_actual(self) -> str:
        # Nombres por ubicación (sistema unificado, sin perfiles).
        if self.impreso:
            return "ok"
        if self.revisado:
            return "imprenta"
        if self.apdf:
            return "apdf"
        if self.corregido:
            return "mandar"
        if self.fotocromia:
            return "final"
        if self.armado:
            return "base"
        if self.asignado:
            return "txt"
        return "vacío"
