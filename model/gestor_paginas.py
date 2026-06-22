# model/gestor_paginas.py

from .pagina import Pagina

class GestorPaginas:
    def __init__(self):
        self.paginas = {i: Pagina(i) for i in range(1, 17)}
        self.pagina_activa = None

    def obtener_pagina(self, numero: int) -> Pagina:
        return self.paginas[numero]

    def set_pagina_activa(self, numero: int):
        self.pagina_activa = numero

    def get_activa(self) -> Pagina:
        if self.pagina_activa:
            return self.paginas[self.pagina_activa]
        return None

    def reset_estado(self):
        for pagina in self.paginas.values():
            pagina.asignado = False
            pagina.armado = False
            pagina.fotocromia = False
            pagina.corregido = False
            pagina.apdf = False
            pagina.revisado = False
            pagina.impreso = False
            

    # gestor_paginas.py

    def asignar(self, numero: int):
        pagina = self.obtener_pagina(numero)
        if pagina:
            pagina.asignado = True

    def asignar_aviso(self, numero_pagina: int, tipo: str):
        """
        Marca la página como aviso del tipo indicado: 'completa', 'media' o 'pie' con el cargador automático de mono
        """
        pagina = self.obtener_pagina(numero_pagina)
        if not pagina:
            return

        if tipo == "completa":
            pagina.aviso_full = True
            pagina.aviso_half = False
            pagina.aviso_footer = False
        elif tipo == "media":
            pagina.aviso_full = False
            pagina.aviso_half = True
            pagina.aviso_footer = False
        elif tipo == "pie":
            pagina.aviso_full = False
            pagina.aviso_half = False
            pagina.aviso_footer = True
