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
    editando: bool = False
    mono_extra: str = ""
    seccion: str = ""
    estado: str = ""

    def estado_actual(self) -> str:
        if self.impreso:
            return "impreso"
        if self.revisado:
            return "revisado"
        if self.apdf:
            return "apdf"
        if self.corregido:
            return "corregido"
        if self.fotocromia:
            return "fotocromia"
        if self.armado:
            return "armado"
        if self.asignado:
            return "asignado"
        if self.azul:
            return "azul"
        return "vacío"
