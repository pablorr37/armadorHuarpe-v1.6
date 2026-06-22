import sys

# Elimina cualquier rastro de simplejson para forzar
# a requests a usar json estándar
for key in list(sys.modules.keys()):
    if key.startswith("simplejson"):
        del sys.modules[key]
