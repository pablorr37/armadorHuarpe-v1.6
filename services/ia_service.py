from openai import OpenAI
import os
from config.config import config_global
from groq import Groq

class AIRewriter:
    def __init__(self):
        key = config_global.openai_api_key
        if not key:
            raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno.")
        #self.client = OpenAI(api_key=key)
        self.client = Groq(api_key=key)
    def reescribir_cuerpo(self, texto: str) -> str:
        """
        Reescribe un cuerpo de noticia manteniendo largo y sentido general.
        """
        prompt = (
            "Reescribe el siguiente texto periodístico en español, "
            "manteniendo el sentido, el largo aproximado y sin agregar datos nuevos. "
            "Conservá nombres propios y textuales.\n\n"
            f"Texto original:\n{texto}\n\n"
            "Texto reescrito:"
        )

        try:
            resp = self.client.chat.completions.create(
                #model="gpt-4.1-mini",
                model = "llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Eres un redactor profesional."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                #max_tokens=3000,
            )
            return resp.choices[0].message.content.strip()

        except Exception as e:
            raise RuntimeError(f"Error al contactar la API: {e}")
